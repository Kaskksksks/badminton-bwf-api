from __future__ import annotations

import csv
import hashlib
import json
import re
from collections import defaultdict
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import (
    BatchStatus,
    DataSource,
    DatasetVersion,
    Event,
    ExcludedSourceRecord,
    IdentityStatus,
    ImportBatch,
    Match,
    MatchGame,
    MatchParticipantContext,
    MatchStatus,
    Participant,
    ParticipantKind,
    ParticipantMember,
    PlayerAlias,
    RawIngestionRecord,
    RecordLineage,
    ReconciliationCase,
    ReconciliationStatus,
    SourceArtifact,
    SourceEntityIdentifier,
    SourceKind,
    StagedImportRecord,
    Tournament,
    TournamentAlias,
    TournamentClassification,
    ValidationStatus,
)

IMPORTER_VERSION = "0.1.0"
EXPECTED_DISCIPLINES = {"MS", "WS", "MD", "WD", "XD"}
EXPECTED_MEMBERS = {"MS": 1, "WS": 1, "MD": 2, "WD": 2, "XD": 2}
GAME_PATTERN = re.compile(r"(?<!\d)(\d{1,2})\s*-\s*(\d{1,2})(?!\d)")


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def stable_hash(value: object) -> str:
    blob = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


def normalize_text(value: str | None) -> str:
    return re.sub(r"\s+", " ", (value or "").strip()).casefold()


def split_team(value: str) -> list[str]:
    return [member.strip() for member in value.split(" / ") if member.strip()]


def parse_bool(value: str) -> bool | None:
    lower = value.strip().casefold()
    if lower == "true":
        return True
    if lower == "false":
        return False
    return None


def parse_games(score: str) -> list[tuple[int, int]]:
    return [(int(a), int(b)) for a, b in GAME_PATTERN.findall(score.replace("–", "-").replace("—", "-"))]


def score_quality(score: str) -> tuple[str, str, list[tuple[int, int]]]:
    games = parse_games(score)
    strict = bool(re.fullmatch(r"\d{1,2}-\d{1,2}(?:\s+\d{1,2}-\d{1,2}){1,2}", score.strip()))
    if not games:
        return "UNPARSEABLE", "INVALID", games
    if any(left < 0 or right < 0 or left > 99 or right > 99 for left, right in games):
        return "OUT_OF_RANGE", "INVALID", games
    if strict:
        return "STRICT", "VALID", games
    return "PARTIAL_OR_NONSTANDARD", "WARNING", games


def row_validation(row: dict[str, str]) -> tuple[str, list[str], list[tuple[int, int]], str, str]:
    errors: list[str] = []
    warnings: list[str] = []
    try:
        date.fromisoformat(row.get("date", ""))
    except ValueError:
        errors.append("date is not ISO YYYY-MM-DD")
    discipline = row.get("discipline", "")
    if discipline not in EXPECTED_DISCIPLINES:
        errors.append("discipline is unsupported")
    if row.get("winner") not in {"1", "2"}:
        errors.append("winner must be 1 or 2")
    if not row.get("tournament", "").strip():
        errors.append("tournament is required")
    for side in ("team1", "team2"):
        count = len(split_team(row.get(side, "")))
        expected = EXPECTED_MEMBERS.get(discipline)
        if expected and count != expected:
            errors.append(f"{side} member count does not match discipline")
    score_status, score_validation, games = score_quality(row.get("score", ""))
    if score_validation == "INVALID":
        errors.append("score is not safely parseable")
    elif score_validation == "WARNING":
        warnings.append("score has nonstandard game representation")
    if not row.get("round", "").strip():
        warnings.append("round is missing")
    if not row.get("host_location", "").strip():
        warnings.append("host location is missing")
    status = ValidationStatus.INVALID.value if errors else (ValidationStatus.WARNING.value if warnings else ValidationStatus.VALID.value)
    return status, errors + warnings, games, score_status, score_validation


def get_or_create_source(session: Session, code: str, source_kind: SourceKind, display_name: str, base_url: str | None = None) -> DataSource:
    source = session.scalar(select(DataSource).where(DataSource.code == code))
    if source:
        return source
    source = DataSource(code=code, source_kind=source_kind.value, display_name=display_name, base_url=base_url)
    session.add(source)
    session.flush()
    return source


def get_or_create_alias(session: Session, source_id: str, alias: str, record_id: str, match_date: date) -> PlayerAlias:
    normalized = normalize_text(alias)
    existing = session.scalar(
        select(PlayerAlias).where(PlayerAlias.source_id == source_id, PlayerAlias.normalized_alias == normalized, PlayerAlias.player_id.is_(None))
    )
    if existing:
        return existing
    alias_row = PlayerAlias(
        source_id=source_id,
        alias_text=alias,
        normalized_alias=normalized,
        valid_from=match_date,
        valid_to=match_date,
        evidence_record_id=record_id,
        resolution_status=IdentityStatus.UNRESOLVED.value,
    )
    session.add(alias_row)
    session.flush()
    return alias_row


def get_or_create_participant(session: Session, source_id: str, team_text: str, record_id: str, match_date: date, discipline: str) -> Participant:
    members = split_team(team_text)
    alias_rows = [get_or_create_alias(session, source_id, member, record_id, match_date) for member in members]
    member_key = sorted(alias.normalized_alias for alias in alias_rows)
    member_hash = stable_hash({"source_id": source_id, "members": member_key})
    kind = ParticipantKind.SINGLES.value if discipline in {"MS", "WS"} else ParticipantKind.PAIR.value
    participant = session.scalar(
        select(Participant).where(Participant.participant_kind == kind, Participant.canonical_member_hash == member_hash)
    )
    if participant:
        return participant
    participant = Participant(
        participant_kind=kind,
        canonical_member_hash=member_hash,
        display_name=team_text,
        identity_resolution_status=IdentityStatus.UNRESOLVED.value,
    )
    session.add(participant)
    session.flush()
    for order, alias_row in enumerate(alias_rows, start=1):
        session.add(
            ParticipantMember(
                participant_id=participant.id,
                player_id=None,
                member_order=order,
                source_alias_text=alias_row.alias_text,
                source_alias_id=alias_row.id,
            )
        )
    session.flush()
    return participant


def get_or_create_tournament(session: Session, source_id: str, row: dict[str, str], record_id: str, match_date: date) -> Tournament:
    # A yearly source key is deliberate: a title alone can represent many annual events.
    raw_name = row["tournament"]
    key = f"{normalize_text(raw_name)}:{match_date.year}"
    identifier = session.scalar(
        select(SourceEntityIdentifier).where(
            SourceEntityIdentifier.source_id == source_id,
            SourceEntityIdentifier.entity_type == "TOURNAMENT",
            SourceEntityIdentifier.identifier_kind == "HISTORICAL_TITLE_YEAR",
            SourceEntityIdentifier.identifier_value == key,
        )
    )
    if identifier:
        return session.get(Tournament, identifier.entity_id)
    tournament = Tournament(name=raw_name, source_name_raw=raw_name, location_raw=row.get("host_location") or None, status="COMPLETED")
    session.add(tournament)
    session.flush()
    session.add(
        SourceEntityIdentifier(
            source_id=source_id,
            entity_type="TOURNAMENT",
            entity_id=tournament.id,
            identifier_kind="HISTORICAL_TITLE_YEAR",
            identifier_value=key,
            confidence="SOURCE_ASSERTED",
            evidence_record_id=None,
        )
    )
    session.add(
        TournamentAlias(
            tournament_id=tournament.id,
            source_id=source_id,
            raw_title=raw_name,
            normalized_title=normalize_text(raw_name),
            evidence_record_id=record_id,
            resolution_status=IdentityStatus.UNRESOLVED.value,
        )
    )
    session.add(
        TournamentClassification(
            tournament_id=tournament.id,
            raw_label=row.get("tier", ""),
            classification_system="HISTORICAL_SEED_TIER",
            normalized_class=None,
            valid_from=match_date,
            valid_to=match_date,
            evidence_record_id=record_id,
        )
    )
    session.flush()
    return tournament


def get_or_create_event(session: Session, tournament: Tournament, discipline: str) -> Event:
    event = session.scalar(select(Event).where(Event.tournament_id == tournament.id, Event.event_type == discipline))
    if event:
        return event
    event = Event(tournament_id=tournament.id, event_type=discipline)
    session.add(event)
    session.flush()
    return event


def register_artifacts(session: Session, root: Path, dataset_version: DatasetVersion, batch: ImportBatch, manifest: dict[str, Any]) -> dict[str, SourceArtifact]:
    roles = {
        "matches.csv": "PRIMARY_MATCH_TABLE",
        "index.json": "TOURNAMENT_CATALOG",
        "extension_match_provenance.csv": "EXTENSION_MATCH_PROVENANCE",
        "excluded_extension_records.csv": "EXTENSION_EXCLUSION_LEDGER",
        "source/official_extension_raw.json": "OFFICIAL_EXTENSION_RAW",
        "manifest.json": "DATASET_MANIFEST",
    }
    artifacts: dict[str, SourceArtifact] = {}
    expected = manifest.get("sha256", {})
    for relative_path, role in roles.items():
        path = root / relative_path
        if not path.exists():
            continue
        actual_hash = sha256_file(path)
        # The in-package manifest has checksums for selected top-level files only.
        expected_hash = expected.get(path.name)
        if expected_hash and expected_hash != actual_hash:
            raise ValueError(f"Checksum mismatch for {relative_path}")
        artifact = SourceArtifact(
            dataset_version_id=dataset_version.id,
            import_batch_id=batch.id,
            logical_role=role,
            original_filename=relative_path,
            sha256=actual_hash,
            byte_size=path.stat().st_size,
            media_type="application/json" if path.suffix == ".json" else "text/csv",
            storage_uri=str(path.resolve()),
        )
        session.add(artifact)
        session.flush()
        artifacts[relative_path] = artifact
    return artifacts


def register_extension_raw_evidence(
    session: Session,
    root: Path,
    source: DataSource,
    batch: ImportBatch,
    artifacts: dict[str, SourceArtifact],
) -> None:
    raw_path = root / "source" / "official_extension_raw.json"
    exclusion_path = root / "excluded_extension_records.csv"
    if not raw_path.exists():
        return
    raw_doc = json.loads(raw_path.read_text(encoding="utf-8"))
    exclusion_reasons: dict[str, dict[str, str]] = {}
    if exclusion_path.exists():
        with exclusion_path.open("r", encoding="utf-8", newline="") as stream:
            for row in csv.DictReader(stream):
                exclusion_reasons[row["match_id"]] = row
    raw_artifact = artifacts.get("source/official_extension_raw.json")
    for day in raw_doc.get("days", []):
        for source_match in day.get("matches", []):
            external_id = str(source_match.get("id"))
            record = RawIngestionRecord(
                import_batch_id=batch.id,
                source_artifact_id=raw_artifact.id if raw_artifact else None,
                source_id=source.id,
                endpoint_key="historical_extension_raw",
                source_record_key=external_id,
                retrieved_at=utcnow(),
                http_status=200,
                content_hash=stable_hash(source_match),
                raw_payload=source_match,
                parser_version=IMPORTER_VERSION,
                reliability=str(source_match.get("reliability")) if source_match.get("reliability") is not None else None,
                processing_status="CAPTURED",
            )
            session.add(record)
            session.flush()
            if external_id in exclusion_reasons:
                reason = exclusion_reasons[external_id]
                session.add(
                    ExcludedSourceRecord(
                        source_record_id=record.id,
                        source_artifact_id=artifacts.get("excluded_extension_records.csv").id if artifacts.get("excluded_extension_records.csv") else None,
                        source_record_key=external_id,
                        exclusion_code="WALKOVER_OR_NO_PLAYED_SCORE",
                        reason=reason.get("reason", "walkover_or_no_played_score"),
                        source_url=reason.get("source_url"),
                    )
                )


def import_historical_seed(session: Session, root: Path) -> ImportBatch:
    """Import the audited package through staging; safe to rerun after a failed batch.

    The caller owns transaction boundaries. A successful version is not imported twice.
    """
    root = Path(root)
    manifest_path = root / "manifest.json"
    matches_path = root / "matches.csv"
    if not manifest_path.exists() or not matches_path.exists():
        raise FileNotFoundError("Historical seed root must contain manifest.json and matches.csv")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    source = get_or_create_source(session, "HISTORICAL_SEED", SourceKind.HISTORICAL_SEED, "Historical seed dataset")
    version = session.scalar(
        select(DatasetVersion).where(
            DatasetVersion.source_id == source.id,
            DatasetVersion.dataset_name == manifest["dataset_name"],
            DatasetVersion.dataset_version == manifest["coverage_end"],
        )
    )
    if version:
        previous = session.scalar(
            select(ImportBatch).where(ImportBatch.dataset_version_id == version.id, ImportBatch.status == BatchStatus.SUCCEEDED.value)
        )
        if previous:
            return previous
    else:
        version = DatasetVersion(
            source_id=source.id,
            dataset_name=manifest["dataset_name"],
            dataset_version=manifest["coverage_end"],
            coverage_start=date.fromisoformat(manifest["coverage_start"]),
            coverage_end=date.fromisoformat(manifest["coverage_end"]),
            manifest_hash=sha256_file(manifest_path),
            license_note="User-supplied historical seed; provenance retained from supplied package.",
            released_at=utcnow(),
        )
        session.add(version)
        session.flush()

    batch = ImportBatch(
        dataset_version_id=version.id,
        batch_type="HISTORICAL_SEED",
        status=BatchStatus.RUNNING.value,
        started_at=utcnow(),
        importer_version=IMPORTER_VERSION,
    )
    session.add(batch)
    session.flush()
    artifacts = register_artifacts(session, root, version, batch, manifest)
    matches_artifact = artifacts["matches.csv"]

    with matches_path.open("r", encoding="utf-8", newline="") as stream:
        reader = csv.DictReader(stream)
        for row_number, row in enumerate(reader, start=2):
            batch.input_row_count += 1
            status, messages, games, score_parse_status, score_validation_status = row_validation(row)
            row_hash = stable_hash(row)
            staged = StagedImportRecord(
                import_batch_id=batch.id,
                source_artifact_id=matches_artifact.id,
                source_row_number=row_number,
                source_record_key=row_hash,
                original_payload=row,
                row_hash=row_hash,
                parser_version=IMPORTER_VERSION,
                validation_status=status,
                reconciliation_status=ReconciliationStatus.PENDING.value,
                validation_messages=messages,
            )
            session.add(staged)
            session.flush()
            if status == ValidationStatus.INVALID.value:
                staged.reconciliation_status = ReconciliationStatus.EXCLUDED.value
                batch.rejected_count += 1
                session.add(
                    ReconciliationCase(
                        import_batch_id=batch.id,
                        case_type="VALIDATION_FAILURE",
                        status=ReconciliationStatus.EXCLUDED.value,
                        source_record_id=staged.id,
                        rationale="; ".join(messages),
                    )
                )
                continue

            match_date = date.fromisoformat(row["date"])
            existing = session.scalar(select(Match).where(Match.source_match_key == row_hash))
            if existing:
                staged.reconciliation_status = ReconciliationStatus.DUPLICATE_EXACT.value
                batch.duplicate_count += 1
                session.add(
                    RecordLineage(
                        source_record_id=staged.id,
                        entity_type="MATCH",
                        entity_id=existing.id,
                        relationship_type="DUPLICATE_EXACT",
                        confidence="HIGH",
                        reason="All source CSV fields produce the same deterministic row hash.",
                    )
                )
                session.add(
                    ReconciliationCase(
                        import_batch_id=batch.id,
                        case_type="EXACT_DUPLICATE",
                        status=ReconciliationStatus.DUPLICATE_EXACT.value,
                        source_record_id=staged.id,
                        candidate_entity_type="MATCH",
                        candidate_entity_id=existing.id,
                        rationale="Exact duplicate historical CSV row; preserved as source evidence.",
                    )
                )
                continue

            tournament = get_or_create_tournament(session, source.id, row, staged.id, match_date)
            event = get_or_create_event(session, tournament, row["discipline"])
            participant_1 = get_or_create_participant(session, source.id, row["team1"], staged.id, match_date, row["discipline"])
            participant_2 = get_or_create_participant(session, source.id, row["team2"], staged.id, match_date, row["discipline"])
            status_value = MatchStatus.COMPLETED.value
            if score_parse_status in {"UNPARSEABLE", "OUT_OF_RANGE", "PARTIAL_OR_NONSTANDARD"} or len(games) not in {2, 3}:
                status_value = MatchStatus.HISTORICAL_PARTIAL.value
            winner = participant_1 if row["winner"] == "1" else participant_2
            match = Match(
                source_match_key=row_hash,
                match_date=match_date,
                tournament_id=tournament.id,
                event_id=event.id,
                round_raw=row.get("round") or None,
                status=status_value,
                participant_1_id=participant_1.id,
                participant_2_id=participant_2.id,
                winner_participant_id=winner.id,
                winner_side_raw=row["winner"],
                score_raw=row.get("score") or None,
                score_parse_status=score_parse_status,
                score_validation_status=score_validation_status,
                completion_basis="HISTORICAL_SEED_ROW",
                source_completeness="PARTIAL" if status_value == MatchStatus.HISTORICAL_PARTIAL.value else "COMPLETE",
                historical_seed_flag=True,
            )
            session.add(match)
            session.flush()
            staged.reconciliation_status = ReconciliationStatus.CANONICAL.value
            batch.accepted_count += 1
            session.add(
                RecordLineage(
                    source_record_id=staged.id,
                    entity_type="MATCH",
                    entity_id=match.id,
                    relationship_type="CANONICAL_SOURCE",
                    confidence="HIGH",
                    reason="Validated source row normalized from the historical seed dataset.",
                )
            )
            for side, participant, home_value in (
                (1, participant_1, parse_bool(row.get("team1_at_home", ""))),
                (2, participant_2, parse_bool(row.get("team2_at_home", ""))),
            ):
                session.add(
                    MatchParticipantContext(
                        match_id=match.id,
                        participant_id=participant.id,
                        side=side,
                        is_home=home_value,
                        source_record_id=staged.id,
                    )
                )
            for game_number, (score_1, score_2) in enumerate(games, start=1):
                game_winner = participant_1.id if score_1 > score_2 else (participant_2.id if score_2 > score_1 else None)
                session.add(
                    MatchGame(
                        match_id=match.id,
                        game_number=game_number,
                        source_game_number=game_number,
                        participant_1_score=score_1,
                        participant_2_score=score_2,
                        winner_participant_id=game_winner,
                        status=status_value,
                        parse_confidence="HIGH" if score_parse_status == "STRICT" else "PARTIAL",
                        source_record_id=staged.id,
                    )
                )

            # Keep commit work bounded during the 94k-row import while retaining atomic rows.
            if batch.input_row_count % 500 == 0:
                session.flush()

    register_extension_raw_evidence(session, root, source, batch, artifacts)
    batch.status = BatchStatus.SUCCEEDED.value
    batch.completed_at = utcnow()
    session.flush()
    return batch
