"""Controlled, opt-in ingestion of ranking lists exposed by BWF's public ranking interface.

The source routes and ranking identifiers were observed from the public BWF ranking page.  They
are not treated as a stable public API: collection is disabled unless an operator explicitly
sets the permission reference and live-source switch.  This module never runs on public reads.
"""

from __future__ import annotations

import hashlib
import json
import logging
from dataclasses import dataclass
from datetime import date, datetime, timezone
from typing import Any, Iterable, Mapping

import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import Settings, get_settings
from app.db.models import (
    BatchStatus,
    DataSource,
    ImportBatch,
    RankingEntry,
    RankingSnapshot,
    RawIngestionRecord,
    SourceKind,
)

logger = logging.getLogger(__name__)

PARSER_VERSION = "bwf-ranking-interface-v1"
SOURCE_CODE = "BWF_OFFICIAL_RANKINGS"
SOURCE_NAME = "BWF official ranking interface"
DISCIPLINES = ("MS", "WS", "MD", "WD", "XD")


@dataclass(frozen=True)
class RankingScope:
    ranking_system: str
    population: str
    ranking_id: int
    first_category_id: int
    discipline: str

    @property
    def category_id(self) -> int:
        return self.first_category_id + DISCIPLINES.index(self.discipline)

    @property
    def is_doubles(self) -> bool:
        return self.discipline in {"MD", "WD", "XD"}


# Senior-only scope: retain World and World Tour rankings across all five disciplines.
# World Junior collection is intentionally excluded under the cost-control policy.
RANKING_FAMILIES: tuple[tuple[str, str, int, int], ...] = (
    ("WORLD", "SENIOR", 2, 6),
    ("WORLD_TOUR", "SENIOR", 9, 57),
)


def requested_scopes() -> tuple[RankingScope, ...]:
    return tuple(
        RankingScope(system, population, ranking_id, first_category_id, discipline)
        for system, population, ranking_id, first_category_id in RANKING_FAMILIES
        for discipline in DISCIPLINES
    )


@dataclass(frozen=True)
class SourceResponse:
    endpoint_key: str
    url: str
    status_code: int
    payload: Any


class BWFRankingClient:
    """A constrained client for BWF routes observed in the public rankings page.

    It accepts only the two fixed source paths and fixed rank/category IDs from
    ``requested_scopes``.  It deliberately has no generic URL-fetching method.
    """

    def __init__(self, settings: Settings | None = None, client: httpx.Client | None = None) -> None:
        self.settings = settings or get_settings()
        self._client = client or httpx.Client(
            base_url=self.settings.bwf_rankings_base_url.rstrip("/"),
            timeout=self.settings.bwf_rankings_request_timeout_seconds,
            headers={
                "Accept": "application/json",
                "User-Agent": self.settings.bwf_rankings_user_agent,
            },
            follow_redirects=False,
        )
        self._owns_client = client is None

    def close(self) -> None:
        if self._owns_client:
            self._client.close()

    def _get(self, endpoint_key: str, path: str, params: Mapping[str, Any]) -> SourceResponse:
        response = self._client.get(path, params=dict(params))
        response.raise_for_status()
        try:
            payload = response.json()
        except ValueError as exc:
            raise ValueError(f"BWF response contract failed for {endpoint_key}: invalid JSON") from exc
        return SourceResponse(endpoint_key=endpoint_key, url=str(response.url), status_code=response.status_code, payload=payload)

    def get_weeks(self, ranking_id: int) -> SourceResponse:
        return self._get("vue-rankingweek", "/api/vue-rankingweek", {"rankId": ranking_id})

    def get_table(self, scope: RankingScope, publication_id: int, page: int, draw_count: int) -> SourceResponse:
        return self._get(
            "vue-rankingtable",
            "/api/vue-rankingtable",
            {
                "rankId": scope.ranking_id,
                "catId": scope.category_id,
                "publicationId": publication_id,
                "doubles": str(scope.is_doubles).lower(),
                "searchKey": "",
                "pageKey": self.settings.bwf_rankings_page_size,
                "page": page,
                "drawCount": draw_count,
            },
        )


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def canonical_hash(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")).hexdigest()


def as_mapping(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def first_present(value: Mapping[str, Any], *keys: str) -> Any:
    for key in keys:
        candidate = value.get(key)
        if candidate is not None and candidate != "":
            return candidate
    return None


def parse_int(value: Any) -> int | None:
    if value is None or value == "":
        return None
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float) and value.is_integer():
        return int(value)
    cleaned = str(value).replace(",", "").replace("+", "").strip()
    if cleaned in {"", "-", "N/A"}:
        return None
    try:
        return int(cleaned)
    except ValueError:
        return None


def parse_effective_date(value: Any) -> date | None:
    if isinstance(value, date) and not isinstance(value, datetime):
        return value
    if isinstance(value, datetime):
        return value.date()
    if not isinstance(value, str):
        return None
    text = value.strip()
    for fmt in ("%Y-%m-%d", "%d/%m/%Y", "%d-%m-%Y", "%Y/%m/%d"):
        try:
            return datetime.strptime(text[:10], fmt).date()
        except ValueError:
            pass
    return None


def extract_latest_publication(weeks_payload: Any) -> tuple[int, date | None, str | None]:
    """Read the first publication supplied by BWF's ranking-week route.

    The public page uses the first result as the current week.  This parser accepts
    known list/dict envelope variants, but rejects a response without a numeric
    publication key rather than silently assuming an arbitrary historic list.
    """

    candidates: Iterable[Any]
    if isinstance(weeks_payload, list):
        candidates = weeks_payload
    elif isinstance(weeks_payload, Mapping):
        candidates = first_present(weeks_payload, "data", "results", "rankings", "weeks") or []
    else:
        candidates = []
    first = next(iter(candidates), None)
    item = as_mapping(first)
    publication_id = parse_int(first_present(item, "publicationId", "publication_id", "id", "key"))
    if publication_id is None:
        # A key can be a compound e.g. `2-6-12345`; the last component is publication id.
        key = first_present(item, "key", "value")
        if isinstance(key, str):
            publication_id = parse_int(key.rsplit("-", 1)[-1])
    if publication_id is None:
        raise ValueError("BWF ranking week contract failed: current publication identifier unavailable")
    effective_date = parse_effective_date(first_present(item, "effectiveDate", "effective_date", "date", "publishedAt", "published_at"))
    label = first_present(item, "label", "text", "name", "week")
    return publication_id, effective_date, str(label) if label is not None else None


def extract_table_rows(payload: Any) -> tuple[list[Mapping[str, Any]], int | None]:
    root = as_mapping(payload)
    results = as_mapping(root.get("results"))
    rows = first_present(results, "data", "items", "rows")
    if rows is None:
        rows = first_present(root, "data", "items", "rows")
    if not isinstance(rows, list):
        raise ValueError("BWF ranking table contract failed: row list unavailable")
    total_pages = parse_int(first_present(results, "last_page", "lastPage", "total_pages", "totalPages"))
    return [as_mapping(item) for item in rows if isinstance(item, Mapping)], total_pages


def normalize_row(scope: RankingScope, row: Mapping[str, Any]) -> dict[str, Any]:
    rank = parse_int(first_present(row, "ranking", "rank", "position", "rankNo", "rankingPosition"))
    if rank is None or rank < 1:
        raise ValueError("BWF ranking row rejected: positive rank required")
    points = parse_int(first_present(row, "points", "point", "rankingPoints", "rank_point"))
    tournaments = parse_int(first_present(row, "tournaments", "tournamentCount", "totalTournament"))
    change = parse_int(first_present(row, "change", "rankChange", "change_rank"))
    player = as_mapping(first_present(row, "player", "athlete", "participant"))
    player_one = as_mapping(first_present(row, "player1_model", "playerOne", "player_1"))
    player_two = as_mapping(first_present(row, "player2_model", "playerTwo", "player_2"))
    direct_display_name = first_present(row, "name", "playerName", "player_name", "displayName", "pairName") or first_present(
        player, "name", "fullName", "displayName"
    )
    player_one_name = first_present(player_one, "name", "fullName", "displayName", "name_display_bold")
    player_two_name = first_present(player_two, "name", "fullName", "displayName", "name_display_bold")
    display_name = direct_display_name
    if display_name is None and scope.is_doubles:
        pair_names = [name.strip() for name in (player_one_name, player_two_name) if isinstance(name, str) and name.strip()]
        display_name = " / ".join(pair_names) if len(pair_names) == 2 else None
    if display_name is None:
        display_name = player_one_name
    if not isinstance(display_name, str) or not display_name.strip():
        raise ValueError("BWF ranking row rejected: display name required")
    official_id = first_present(row, "team_id", "teamId") if scope.is_doubles else None
    official_id = official_id or first_present(row, "playerId", "player_id", "player1_id", "bwfId", "bwf_id", "id") or first_present(
        player, "id", "playerId", "bwfId"
    ) or first_present(player_one, "id", "playerId", "bwfId")
    country_one = first_present(row, "countryCode", "country_code", "country", "nation") or first_present(
        player, "countryCode", "country"
    ) or first_present(as_mapping(row.get("p1_country_model")), "code", "countryCode", "name")
    country_two = first_present(as_mapping(row.get("p2_country_model")), "code", "countryCode", "name")
    country = country_one if not scope.is_doubles or country_one == country_two else None
    subject_kind = "PAIR" if scope.is_doubles else "PLAYER"
    subject_key = str(official_id) if official_id is not None else f"{scope.discipline}:{display_name.strip().upper()}:{country or ''}"
    return {
        "ranking_position": rank,
        "points": points,
        "tournament_count": tournaments,
        "rank_change": change,
        "subject_kind": subject_kind,
        "subject_key": subject_key,
        "subject_display_name": display_name.strip(),
        "official_subject_id": str(official_id) if official_id is not None else None,
        "country_code": str(country).strip().upper()[:8] if country else None,
        # The BWF identifier is source evidence, not proof that the platform's
        # historical alias denotes this player.  Identity remains unresolved.
        "identity_status": "UNRESOLVED",
        "source_payload": dict(row),
    }


def get_or_create_source(session: Session, settings: Settings) -> DataSource:
    source = session.scalar(select(DataSource).where(DataSource.code == SOURCE_CODE))
    if source:
        return source
    source = DataSource(
        code=SOURCE_CODE,
        source_kind=SourceKind.BWF_RANKINGS.value,
        display_name=SOURCE_NAME,
        base_url=settings.bwf_rankings_base_url.rstrip("/"),
        active=True,
    )
    session.add(source)
    session.flush()
    return source


def create_batch(session: Session) -> ImportBatch:
    batch = ImportBatch(
        batch_type="BWF_RANKINGS_WEEKLY",
        status=BatchStatus.RUNNING.value,
        started_at=utcnow(),
        importer_version=PARSER_VERSION,
    )
    session.add(batch)
    session.flush()
    return batch


def persist_scope(
    session: Session,
    source: DataSource,
    batch: ImportBatch,
    scope: RankingScope,
    response_url: str,
    publication_id: int,
    effective_date: date,
    published_week: str | None,
    rows: list[dict[str, Any]],
    source_payload: dict[str, Any],
    settings: Settings,
) -> tuple[bool, int]:
    content_hash = canonical_hash(source_payload)
    existing = session.scalar(
        select(RankingSnapshot).where(
            RankingSnapshot.ranking_system == scope.ranking_system,
            RankingSnapshot.discipline == scope.discipline,
            RankingSnapshot.effective_date == effective_date,
            RankingSnapshot.content_hash == content_hash,
        )
    )
    if existing:
        return False, 0
    raw = RawIngestionRecord(
        import_batch_id=batch.id,
        source_id=source.id,
        endpoint_key="vue-rankingtable",
        request_fingerprint=canonical_hash({"scope": scope.__dict__, "publication_id": publication_id}),
        source_record_key=f"{scope.ranking_system}:{scope.discipline}:{effective_date.isoformat()}:{publication_id}",
        retrieved_at=utcnow(),
        http_status=200,
        content_hash=content_hash,
        raw_payload=source_payload,
        payload_uri=response_url,
        parser_version=PARSER_VERSION,
        reliability="OFFICIAL_INTERFACE",
        processing_status="ACCEPTED",
    )
    session.add(raw)
    session.flush()
    snapshot = RankingSnapshot(
        source_id=source.id,
        import_batch_id=batch.id,
        source_record_id=raw.id,
        ranking_system=scope.ranking_system,
        population=scope.population,
        discipline=scope.discipline,
        effective_date=effective_date,
        published_week=published_week,
        source_url=response_url,
        retrieved_at=utcnow(),
        content_hash=content_hash,
        parser_version=PARSER_VERSION,
        snapshot_status="COMPLETE",
        entry_count=len(rows),
        issue_summary=None,
    )
    session.add(snapshot)
    session.flush()
    for row in rows:
        session.add(RankingEntry(snapshot_id=snapshot.id, **row))
    return True, len(rows)


def ensure_live_collection_allowed(settings: Settings) -> None:
    if not settings.bwf_rankings_enabled:
        raise RuntimeError("BWF rankings collection is disabled; set BWF_RANKINGS_ENABLED=true only after permission/licensing is confirmed")
    if not settings.bwf_rankings_allow_live_source:
        raise RuntimeError("live BWF rankings collection blocked; set BWF_RANKINGS_ALLOW_LIVE_SOURCE=true only after source validation")
    if settings.bwf_rankings_permission_required and not settings.bwf_rankings_permission_reference:
        raise RuntimeError("BWF_RANKINGS_PERMISSION_REFERENCE is required before live collection")


def diagnose_ranking_row_shape(
    discipline: str = "MS", settings: Settings | None = None, client: BWFRankingClient | None = None
) -> dict[str, Any]:
    """Return key-only diagnostics for one authorized senior ranking response without persisting it."""

    settings = settings or get_settings()
    ensure_live_collection_allowed(settings)
    owns_client = client is None
    client = client or BWFRankingClient(settings)
    try:
        scope = next(
            (
                candidate
                for candidate in requested_scopes()
                if candidate.ranking_system == "WORLD" and candidate.discipline == discipline
            ),
            None,
        )
        if scope is None:
            raise ValueError(f"unsupported ranking diagnostic discipline: {discipline}")
        publication_id, effective_date, published_week = extract_latest_publication(client.get_weeks(scope.ranking_id).payload)
        response = client.get_table(scope, publication_id, page=1, draw_count=1)
        rows, total_pages = extract_table_rows(response.payload)
        if not rows:
            raise ValueError("BWF ranking shape diagnostic found no rows")
        first_row = rows[0]
        nested_mapping_keys = {
            str(key): sorted(str(nested_key) for nested_key in value.keys())
            for key, value in first_row.items()
            if isinstance(value, Mapping)
        }
        return {
            "scope": scope.__dict__,
            "publication_id": publication_id,
            "effective_date": effective_date.isoformat() if effective_date else None,
            "published_week": published_week,
            "response_url": response.url,
            "row_count_on_first_page": len(rows),
            "total_pages": total_pages,
            "row_keys": sorted(str(key) for key in first_row.keys()),
            "nested_mapping_keys": nested_mapping_keys,
        }
    finally:
        if owns_client:
            client.close()


def synchronize_rankings(session: Session, settings: Settings | None = None, client: BWFRankingClient | None = None) -> dict[str, int | str]:
    """Fetch and store the ten requested senior ranking scopes as immutable snapshots."""

    settings = settings or get_settings()
    ensure_live_collection_allowed(settings)
    owns_client = client is None
    client = client or BWFRankingClient(settings)
    batch = create_batch(session)
    created_scopes = 0
    duplicate_scopes = 0
    accepted_entries = 0
    rejected_scopes = 0
    try:
        source = get_or_create_source(session, settings)
        publication_cache: dict[int, tuple[int, date | None, str | None]] = {}
        for scope in requested_scopes():
            try:
                if scope.ranking_id not in publication_cache:
                    publication_cache[scope.ranking_id] = extract_latest_publication(client.get_weeks(scope.ranking_id).payload)
                publication_id, source_date, published_week = publication_cache[scope.ranking_id]
                page = 1
                draw_count = 0
                all_rows: list[dict[str, Any]] = []
                raw_pages: list[dict[str, Any]] = []
                effective_date = source_date
                response_url = ""
                total_pages: int | None = None
                while total_pages is None or page <= total_pages:
                    if page > settings.bwf_rankings_max_pages_per_scope:
                        raise ValueError("BWF ranking pagination exceeded configured page limit")
                    draw_count += 1
                    response = client.get_table(scope, publication_id, page, draw_count)
                    rows, reported_total_pages = extract_table_rows(response.payload)
                    raw_pages.append(as_mapping(response.payload))
                    response_url = response.url
                    normalized = [normalize_row(scope, row) for row in rows]
                    all_rows.extend(normalized)
                    if len(all_rows) > settings.bwf_rankings_max_entries_per_scope:
                        raise ValueError("BWF ranking entry count exceeded configured scope limit")
                    total_pages = reported_total_pages or page
                    if not rows or page >= total_pages:
                        break
                    page += 1
                if not all_rows:
                    raise ValueError("BWF ranking scope contained no rows")
                if effective_date is None:
                    raise ValueError("BWF ranking week contract failed: effective date unavailable")
                created, count = persist_scope(
                    session, source, batch, scope, response_url, publication_id, effective_date, published_week,
                    all_rows, {"publication_id": publication_id, "scope": scope.__dict__, "pages": raw_pages}, settings,
                )
                if created:
                    created_scopes += 1
                    accepted_entries += count
                else:
                    duplicate_scopes += 1
            except Exception as scope_exc:
                rejected_scopes += 1
                logger.exception("bwf_ranking_scope_failed", extra={"scope": scope.__dict__})
                # Preserve valid completed scopes and record the failure in the batch.
                batch.error_summary = (batch.error_summary or "") + f"{scope.ranking_system}/{scope.discipline}: {scope_exc}; "
        batch.input_row_count = accepted_entries
        batch.accepted_count = accepted_entries
        batch.rejected_count = rejected_scopes
        batch.duplicate_count = duplicate_scopes
        batch.completed_at = utcnow()
        batch.status = BatchStatus.SUCCEEDED.value if created_scopes or duplicate_scopes else BatchStatus.FAILED.value
        session.flush()
        if batch.status == BatchStatus.FAILED.value:
            raise RuntimeError(batch.error_summary or "no ranking scope was imported")
        return {
            "status": "ok",
            "batch_id": batch.id,
            "created_scopes": created_scopes,
            "duplicate_scopes": duplicate_scopes,
            "accepted_entries": accepted_entries,
            "rejected_scopes": rejected_scopes,
        }
    except Exception as exc:
        batch.status = BatchStatus.FAILED.value
        batch.error_summary = str(exc)
        batch.completed_at = utcnow()
        session.flush()
        raise
    finally:
        if owns_client:
            client.close()


def run_rankings_job() -> None:
    """APScheduler entry point. It opens one transaction and never touches live polling."""

    from app.db.base import SessionLocal

    settings = get_settings()
    if not settings.bwf_rankings_scheduler_enabled:
        logger.info("bwf_rankings_job_skipped", extra={"reason": "scheduler_disabled"})
        return
    try:
        with SessionLocal.begin() as session:
            result = synchronize_rankings(session, settings=settings)
        logger.info("bwf_rankings_job_complete", extra=result)
    except Exception:
        logger.exception("bwf_rankings_job_failed")
        raise
