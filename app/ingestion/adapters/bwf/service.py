from __future__ import annotations

import hashlib
import json
from datetime import date, datetime, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import Settings, get_settings
from app.db.models import (
    DataSource,
    Event,
    IdentityStatus,
    Match,
    MatchGame,
    MatchStatus,
    Participant,
    ParticipantKind,
    ParticipantMember,
    Player,
    RawIngestionRecord,
    SourceEntityIdentifier,
    SourceKind,
    Tournament,
)
from app.ingestion.adapters.bwf.client import BWFClient, BWFResponse
from app.ingestion.adapters.bwf.eligibility import (
    is_junior_match,
    is_junior_tournament,
    is_paralympic_match,
    is_paralympic_tournament,
)
from app.ingestion.approved_scope import classify_approved_senior_scope
from app.snapshots.service import record_game_state

PARSER_VERSION = "bwf-match-centre-v1"


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def digest(payload: object) -> str:
    raw = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def name_for_player(model: dict[str, Any]) -> str:
    return str(model.get("fullName") or model.get("name_display") or model.get("nameDisplay") or "Unknown player")


def get_bwf_source(session: Session, settings: Settings) -> DataSource:
    source = session.scalar(select(DataSource).where(DataSource.code == "BWF_LIVE"))
    if source:
        return source
    source = DataSource(
        code="BWF_LIVE",
        source_kind=SourceKind.BWF_LIVE.value,
        display_name="BWF Match Centre live interface",
        base_url=settings.bwf_live_base_url,
    )
    session.add(source)
    session.flush()
    return source


def get_entity_by_identifier(
    session: Session, source_id: str, entity_type: str, identifier_kind: str, identifier_value: str
) -> str | None:
    identifier = session.scalar(
        select(SourceEntityIdentifier).where(
            SourceEntityIdentifier.source_id == source_id,
            SourceEntityIdentifier.entity_type == entity_type,
            SourceEntityIdentifier.identifier_kind == identifier_kind,
            SourceEntityIdentifier.identifier_value == identifier_value,
        )
    )
    return identifier.entity_id if identifier else None


def assign_identifier(
    session: Session,
    source_id: str,
    entity_type: str,
    entity_id: str,
    identifier_kind: str,
    identifier_value: str,
    evidence_record_id: str,
) -> None:
    existing = session.scalar(
        select(SourceEntityIdentifier).where(
            SourceEntityIdentifier.source_id == source_id,
            SourceEntityIdentifier.entity_type == entity_type,
            SourceEntityIdentifier.identifier_kind == identifier_kind,
            SourceEntityIdentifier.identifier_value == identifier_value,
        )
    )
    if existing is None:
        session.add(
            SourceEntityIdentifier(
                source_id=source_id,
                entity_type=entity_type,
                entity_id=entity_id,
                identifier_kind=identifier_kind,
                identifier_value=identifier_value,
                confidence="SOURCE_ASSERTED",
                evidence_record_id=evidence_record_id,
            )
        )


def capture_response(session: Session, source: DataSource, response: BWFResponse, source_record_key: str | None = None) -> RawIngestionRecord:
    raw = RawIngestionRecord(
        source_id=source.id,
        endpoint_key=response.endpoint_key,
        request_fingerprint=response.url,
        source_record_key=source_record_key,
        retrieved_at=utcnow(),
        http_status=response.status_code,
        content_hash=digest(response.payload),
        raw_payload=response.payload,
        parser_version=PARSER_VERSION,
        processing_status="CAPTURED",
    )
    session.add(raw)
    session.flush()
    return raw


def upsert_tournament(session: Session, source: DataSource, payload: dict[str, Any], raw: RawIngestionRecord) -> Tournament:
    source_id = str(payload["id"])
    existing_id = get_entity_by_identifier(session, source.id, "TOURNAMENT", "BWF_TOURNAMENT_ID", source_id)
    tournament = session.get(Tournament, existing_id) if existing_id else None
    if tournament is None:
        tournament = Tournament(name=str(payload.get("name") or f"BWF tournament {source_id}"))
        session.add(tournament)
        session.flush()
        assign_identifier(session, source.id, "TOURNAMENT", tournament.id, "BWF_TOURNAMENT_ID", source_id, raw.id)
    tournament.name = str(payload.get("name") or tournament.name)
    tournament.source_name_raw = str(payload.get("name") or tournament.source_name_raw or tournament.name)
    tournament.source_category_raw = str(payload.get("category") or payload.get("classification") or tournament.source_category_raw or "") or None
    tournament.location_raw = str(payload.get("venue_name") or payload.get("venue_address1") or tournament.location_raw or "") or None
    tournament.source_url = payload.get("tmtLink") or tournament.source_url
    start_date = payload.get("start_date")
    end_date = payload.get("end_date")
    if isinstance(start_date, str) and len(start_date) >= 10:
        tournament.start_date = date.fromisoformat(start_date[:10])
    if isinstance(end_date, str) and len(end_date) >= 10:
        tournament.end_date = date.fromisoformat(end_date[:10])
    tournament.status = "ACTIVE"
    session.flush()
    return tournament


def upsert_player(session: Session, source: DataSource, payload: dict[str, Any], raw: RawIngestionRecord) -> Player:
    source_player_id = str(payload["id"])
    existing_id = get_entity_by_identifier(session, source.id, "PLAYER", "BWF_PLAYER_ID", source_player_id)
    player = session.get(Player, existing_id) if existing_id else None
    if player is None:
        player = Player(full_name=name_for_player(payload), identity_status=IdentityStatus.CONFIRMED.value)
        session.add(player)
        session.flush()
        assign_identifier(session, source.id, "PLAYER", player.id, "BWF_PLAYER_ID", source_player_id, raw.id)
    player.full_name = name_for_player(payload)
    player.first_name = payload.get("first_name") or payload.get("firstName") or player.first_name
    player.last_name = payload.get("last_name") or payload.get("lastName") or player.last_name
    player.country_code = payload.get("nationality") or payload.get("countryCode") or player.country_code
    player.country_name = payload.get("countryName") or player.country_name
    player.profile_url = payload.get("playerLink") or player.profile_url
    player.identity_status = IdentityStatus.CONFIRMED.value
    player.last_identity_verified_at = utcnow()
    session.flush()
    return player


def upsert_bwf_participant(session: Session, source: DataSource, player_models: list[dict[str, Any]], raw: RawIngestionRecord) -> Participant:
    players = [upsert_player(session, source, item, raw) for item in player_models if isinstance(item, dict) and item.get("id") is not None]
    if not players:
        raise ValueError("BWF live match participant has no source player IDs")
    kind = ParticipantKind.SINGLES.value if len(players) == 1 else ParticipantKind.PAIR.value
    ordered_ids = sorted(player.id for player in players)
    member_hash = digest({"source": source.id, "players": ordered_ids})
    participant = session.scalar(
        select(Participant).where(Participant.participant_kind == kind, Participant.canonical_member_hash == member_hash)
    )
    if participant is None:
        participant = Participant(
            participant_kind=kind,
            canonical_member_hash=member_hash,
            display_name=" / ".join(player.full_name for player in players),
            identity_resolution_status=IdentityStatus.CONFIRMED.value,
        )
        session.add(participant)
        session.flush()
        for member_order, player in enumerate(players, start=1):
            session.add(ParticipantMember(participant_id=participant.id, player_id=player.id, member_order=member_order))
    session.flush()
    return participant


def match_status(live_detail: dict[str, Any]) -> str:
    raw = str(live_detail.get("match_state") or live_detail.get("match_state_name") or "").casefold()
    if raw in {"p", "in progress", "live"}:
        return MatchStatus.LIVE.value
    if raw in {"f", "finished", "completed"}:
        return MatchStatus.COMPLETED.value
    return MatchStatus.UNKNOWN.value


def list_team_models(detail: dict[str, Any], side: int) -> list[dict[str, Any]]:
    models: list[dict[str, Any]] = []
    for player_slot in (1, 2):
        model = detail.get(f"t{side}p{player_slot}_player_model")
        if isinstance(model, dict) and model.get("id") is not None:
            models.append(model)
    return models


def upsert_live_match(session: Session, source: DataSource, tournament: Tournament, envelope: dict[str, Any], raw: RawIngestionRecord) -> Match:
    live = envelope.get("live_detail") or {}
    detail = envelope.get("match_detail") or {}
    source_match_id = str(detail.get("id") or "")
    if not source_match_id:
        raise ValueError("BWF live match payload missing canonical match_detail.id")
    key = f"BWF_LIVE:{source_match_id}"
    match = session.scalar(select(Match).where(Match.source_match_key == key))
    p1 = upsert_bwf_participant(session, source, list_team_models(detail, 1), raw)
    p2 = upsert_bwf_participant(session, source, list_team_models(detail, 2), raw)
    event_type = str(live.get("event") or "UNKNOWN")
    event = session.scalar(select(Event).where(Event.tournament_id == tournament.id, Event.event_type == event_type))
    if event is None:
        event = Event(tournament_id=tournament.id, event_type=event_type)
        session.add(event)
        session.flush()
    if match is None:
        match = Match(
            source_match_key=key,
            match_date=date.today(),
            tournament_id=tournament.id,
            event_id=event.id,
            completion_basis="BWF_OFFICIAL_RESPONSE",
            source_completeness="PARTIAL",
            historical_seed_flag=False,
        )
        session.add(match)
        session.flush()
        assign_identifier(session, source.id, "MATCH", match.id, "BWF_MATCH_ID", source_match_id, raw.id)
    match.tournament_id = tournament.id
    match.event_id = event.id
    match.round_raw = live.get("round") or match.round_raw
    match.court_code = live.get("court_code") or match.court_code
    match.court_name = live.get("court_name") or match.court_name
    match.status = match_status(live)
    match.participant_1_id = p1.id
    match.participant_2_id = p2.id
    match.match_duration_seconds = int(live["duration"] * 60) if isinstance(live.get("duration"), (int, float)) else match.match_duration_seconds
    session.flush()

    # The observed BWF route exposes current G1-G3 totals, not a rally stream.
    for game_number in (1, 2, 3):
        score_1 = live.get(f"team1_g{game_number}_score")
        score_2 = live.get(f"team2_g{game_number}_score")
        if score_1 is None or score_2 is None:
            continue
        game = session.scalar(select(MatchGame).where(MatchGame.match_id == match.id, MatchGame.game_number == game_number))
        if game is None:
            game = MatchGame(
                match_id=match.id,
                game_number=game_number,
                source_game_number=game_number,
                participant_1_score=int(score_1),
                participant_2_score=int(score_2),
                status=match.status,
                parse_confidence="SOURCE_ASSERTED",
            )
            session.add(game)
        else:
            game.participant_1_score = int(score_1)
            game.participant_2_score = int(score_2)
            game.status = match.status
        session.flush()
        record_game_state(
            session,
            match_id=match.id,
            game_number=game_number,
            participant_1_score=int(score_1),
            participant_2_score=int(score_2),
            match_status=match.status,
            raw_record=raw,
            observed_at=raw.retrieved_at,
            court_code=match.court_code,
            service_side=live.get("service_player") if isinstance(live.get("service_player"), int) else None,
        )
    return match


def synchronize_current_bwf(session: Session, client: BWFClient | None = None, settings: Settings | None = None) -> dict[str, int | str]:
    """Fetch current tournaments then live matches after the approved seed boundary."""
    settings = settings or get_settings()
    if date.today() < settings.bwf_ingestion_start_date:
        return {"status": "cutover_not_reached", "tournaments": 0, "live_matches": 0}
    owned_client = client is None
    client = client or BWFClient(settings)
    source = get_bwf_source(session, settings)
    tournaments_response = client.list_current_tournaments()
    tournament_raw = capture_response(session, source, tournaments_response)
    live_match_count = 0
    eligible_tournament_count = 0
    skipped_paralympic_tournament_count = 0
    skipped_paralympic_match_count = 0
    skipped_junior_tournament_count = 0
    skipped_junior_match_count = 0
    skipped_non_target_senior_tournament_count = 0
    skipped_non_target_senior_match_count = 0
    tournaments = tournaments_response.payload.get("results") or []
    for tournament_payload in tournaments:
        if not isinstance(tournament_payload, dict) or tournament_payload.get("id") is None:
            continue
        scope_status, _ = classify_approved_senior_scope(tournament_payload)
        if scope_status == "EXCLUDED_PARA":
            skipped_paralympic_tournament_count += 1
            continue
        if scope_status == "EXCLUDED_JUNIOR":
            skipped_junior_tournament_count += 1
            continue
        if scope_status != "ELIGIBLE":
            skipped_non_target_senior_tournament_count += 1
            continue
        eligible_tournament_count += 1
        tournament = upsert_tournament(session, source, tournament_payload, tournament_raw)
        live_response = client.list_live_matches(tournament_payload["id"])
        live_raw = capture_response(session, source, live_response, source_record_key=str(tournament_payload["id"]))
        for envelope in live_response.payload.get("results") or []:
            if not isinstance(envelope, dict):
                continue
            match_scope_status, _ = classify_approved_senior_scope(tournament_payload, envelope)
            if match_scope_status == "EXCLUDED_PARA":
                skipped_paralympic_match_count += 1
                continue
            if match_scope_status == "EXCLUDED_JUNIOR":
                skipped_junior_match_count += 1
                continue
            if match_scope_status != "ELIGIBLE":
                skipped_non_target_senior_match_count += 1
                continue
            upsert_live_match(session, source, tournament, envelope, live_raw)
            live_match_count += 1
    if owned_client:
        client.close()
    return {
        "status": "ok",
        "tournaments": eligible_tournament_count,
        "live_matches": live_match_count,
        "skipped_paralympic_tournaments": skipped_paralympic_tournament_count,
        "skipped_paralympic_matches": skipped_paralympic_match_count,
        "skipped_junior_tournaments": skipped_junior_tournament_count,
        "skipped_junior_matches": skipped_junior_match_count,
        "skipped_non_target_senior_tournaments": skipped_non_target_senior_tournament_count,
        "skipped_non_target_senior_matches": skipped_non_target_senior_match_count,
    }
