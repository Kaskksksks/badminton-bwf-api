"""Authorised BWF player-profile evidence collection and conservative identity resolution.

This module is deliberately opt-in. It never runs on a public read endpoint, never
accepts arbitrary URLs, and stops on source access denial or rate limiting. It
creates auditable canonical BWF profiles, then resolves historical aliases only
according to documented deterministic rules.
"""
from __future__ import annotations

import hashlib
import json
import html
import logging
import re
import time
import unicodedata
from dataclasses import dataclass
from datetime import date, datetime, timezone
from typing import Any, Mapping

import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import Settings, get_settings
from app.db.models import (
    BatchStatus,
    DataSource,
    ImportBatch,
    ParticipantMember,
    Player,
    PlayerAlias,
    PlayerIdentityLink,
    PlayerProfileSnapshot,
    RawIngestionRecord,
    ReconciliationCase,
    SourceEntityIdentifier,
    SourceKind,
)

logger = logging.getLogger(__name__)
PARSER_VERSION = "bwf-player-profile-interface-v1"
RESOLVER_VERSION = "bwf-profile-auto-resolver-v2"
SOURCE_CODE = "BWF_OFFICIAL_PLAYER_PROFILES"
SOURCE_NAME = "BWF official player profiles"


class SourceAccessStopped(RuntimeError):
    """Collection must stop, rather than retry around an upstream access control."""


@dataclass(frozen=True)
class SourceResponse:
    endpoint_key: str
    url: str
    status_code: int
    payload: Any


@dataclass(frozen=True)
class Candidate:
    bwf_profile_id: str
    display_name: str | None
    country_code: str | None


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def canonical_hash(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")).hexdigest()


def normalize_name(value: str | None) -> str:
    if not value:
        return ""
    decomposed = unicodedata.normalize("NFKD", value)
    plain = "".join(char for char in decomposed if not unicodedata.combining(char))
    return " ".join("".join(char if char.isalnum() else " " for char in plain).upper().split())


def parse_date(value: Any) -> date | None:
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).date()
    except ValueError:
        try:
            return datetime.strptime(value[:10], "%Y-%m-%d").date()
        except ValueError:
            return None


def as_mapping(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def first_present(value: Mapping[str, Any], *keys: str) -> Any:
    for key in keys:
        candidate = value.get(key)
        if candidate not in (None, ""):
            return candidate
    return None


def strip_html_text(value: Any) -> str | None:
    """Convert BWF's observed highlighted name markup to deterministic plain text."""
    if not isinstance(value, str):
        return None
    plain = re.sub(r"<[^>]+>", " ", html.unescape(value))
    plain = " ".join(plain.split())
    return plain or None


def candidate_country_code(country: Mapping[str, Any]) -> str | None:
    direct = first_present(country, "code_iso3", "code", "country_code")
    if direct:
        return str(direct).upper()[:8]
    # The observed h2h search response supplies country name plus a flag URL,
    # such as .../KOR.png. Use only that explicit source component, never infer
    # a code from the country display name.
    flag_url = first_present(country, "flag_url_thumbnail", "flag_url", "flag")
    match = re.search(r"/([A-Za-z]{3})\.png(?:[?#]|$)", str(flag_url)) if flag_url else None
    return match.group(1).upper() if match else None


class BWFPlayerProfileClient:
    """Constrained client for the two official player routes observed in the BWF UI."""

    def __init__(self, settings: Settings | None = None, client: httpx.Client | None = None) -> None:
        self.settings = settings or get_settings()
        self._client = client or httpx.Client(
            base_url=self.settings.bwf_player_profiles_base_url.rstrip("/"),
            timeout=self.settings.bwf_player_profiles_request_timeout_seconds,
            headers={"Accept": "application/json", "User-Agent": self.settings.bwf_player_profiles_user_agent},
            follow_redirects=False,
        )
        self._owns_client = client is None
        self._last_request_at: float | None = None

    def close(self) -> None:
        if self._owns_client:
            self._client.close()

    def _wait(self) -> None:
        if self._last_request_at is None:
            return
        wait = self.settings.bwf_player_profiles_min_request_interval_seconds - (time.monotonic() - self._last_request_at)
        if wait > 0:
            time.sleep(wait)

    def _get(self, endpoint_key: str, path: str, params: Mapping[str, Any]) -> SourceResponse:
        self._wait()
        response = self._client.get(path, params=dict(params))
        self._last_request_at = time.monotonic()
        if response.status_code in {401, 403, 429, 503}:
            raise SourceAccessStopped(f"BWF player source stopped collection: HTTP {response.status_code} at {endpoint_key}")
        response.raise_for_status()
        try:
            payload = response.json()
        except ValueError as exc:
            raise ValueError(f"BWF player source contract failed at {endpoint_key}: invalid JSON") from exc
        return SourceResponse(endpoint_key, str(response.url), response.status_code, payload)

    def search(self, alias_text: str) -> SourceResponse:
        return self._get("h2h-player-search", "/api/h2h/player-search", {"query": alias_text})

    def summary(self, bwf_profile_id: str) -> SourceResponse:
        return self._get("vue-player-summary", "/api/vue-player-summary", {"drawCount": 1, "playerId": bwf_profile_id, "isPara": 0})


def ensure_collection_allowed(settings: Settings) -> None:
    if not settings.bwf_player_profiles_enabled:
        raise RuntimeError("BWF player-profile collection is disabled")
    if not settings.bwf_player_profiles_allow_live_source:
        raise RuntimeError("BWF player-profile live source is not authorised by configuration")
    if settings.bwf_player_profiles_permission_required and not settings.bwf_player_profiles_permission_reference:
        raise RuntimeError("BWF player-profile permission reference is required")


def get_or_create_source(session: Session, settings: Settings) -> DataSource:
    source = session.scalar(select(DataSource).where(DataSource.code == SOURCE_CODE))
    if source:
        return source
    source = DataSource(
        code=SOURCE_CODE,
        source_kind="BWF_PLAYER_PROFILES",
        display_name=SOURCE_NAME,
        base_url=settings.bwf_player_profiles_base_url,
        active=True,
    )
    session.add(source)
    session.flush()
    return source


def extract_candidates(payload: Any) -> list[Candidate]:
    rows = payload if isinstance(payload, list) else first_present(as_mapping(payload), "results", "data", "items") or []
    if not isinstance(rows, list):
        raise ValueError("BWF player search contract failed: candidate list unavailable")
    candidates: list[Candidate] = []
    for raw in rows:
        item = as_mapping(raw)
        profile_id = first_present(item, "id", "playerId", "player_id")
        if profile_id is None:
            continue
        country = as_mapping(first_present(item, "nationality_item", "country_model", "country"))
        display = first_present(item, "name_display", "name", "full_name", "display_name")
        if display is None:
            display = strip_html_text(first_present(item, "name_display_bold", "name_bold"))
        candidates.append(Candidate(str(profile_id), str(display) if display else None, candidate_country_code(country)))
    return candidates


def extract_profile(payload: Any) -> dict[str, Any]:
    profile = as_mapping(first_present(as_mapping(payload), "results", "data"))
    profile_id = first_present(profile, "id", "playerId", "player_id")
    name = first_present(profile, "name_display", "name", "full_name")
    if profile_id is None or not isinstance(name, str) or not name.strip():
        raise ValueError("BWF player summary contract failed: profile ID and name are required")
    country = as_mapping(first_present(profile, "country_model", "country", "nationality_item"))
    country_code = first_present(country, "code_iso3", "code", "country_code") or first_present(profile, "nationality", "country_code")
    return {
        "bwf_profile_id": str(profile_id),
        "full_name": name.strip(),
        "first_name": first_present(profile, "first_name", "firstName"),
        "last_name": first_present(profile, "last_name", "lastName"),
        "country_code": str(country_code).upper()[:8] if country_code else None,
        "bwf_nationality_code": str(first_present(profile, "nationality")).upper()[:8] if first_present(profile, "nationality") else None,
        "country_name": first_present(country, "name", "country_name"),
        "date_of_birth": parse_date(first_present(profile, "date_of_birth", "dob")),
        "profile_type": str(first_present(profile, "profile_type", "profileType")) if first_present(profile, "profile_type", "profileType") is not None else None,
        "payload": dict(profile),
    }


def persist_raw(session: Session, source: DataSource, response: SourceResponse) -> RawIngestionRecord:
    record = RawIngestionRecord(
        source_id=source.id,
        endpoint_key=response.endpoint_key,
        request_fingerprint=canonical_hash({"endpoint": response.endpoint_key, "url": response.url}),
        source_record_key=response.url,
        retrieved_at=utcnow(),
        http_status=response.status_code,
        content_hash=canonical_hash(response.payload),
        raw_payload=response.payload if isinstance(response.payload, (dict, list)) else {"value": response.payload},
        parser_version=PARSER_VERSION,
        reliability="OFFICIAL_PROFILE_SOURCE",
        processing_status="STORED",
    )
    session.add(record)
    session.flush()
    return record


def upsert_canonical_profile(session: Session, source: DataSource, response: SourceResponse) -> tuple[Player, PlayerProfileSnapshot]:
    raw = persist_raw(session, source, response)
    profile = extract_profile(response.payload)
    identifier = session.scalar(select(SourceEntityIdentifier).where(
        SourceEntityIdentifier.source_id == source.id,
        SourceEntityIdentifier.entity_type == "PLAYER",
        SourceEntityIdentifier.identifier_kind == "BWF_PROFILE_ID",
        SourceEntityIdentifier.identifier_value == profile["bwf_profile_id"],
    ))
    player = session.get(Player, identifier.entity_id) if identifier else None
    if player is None:
        player = Player(
            full_name=profile["full_name"], first_name=profile["first_name"], last_name=profile["last_name"],
            country_code=profile["country_code"], country_name=profile["country_name"], date_of_birth=profile["date_of_birth"],
            profile_url=f"https://bwfbadminton.com/player/{profile['bwf_profile_id']}", identity_status="CONFIRMED", last_identity_verified_at=utcnow(),
        )
        session.add(player)
        session.flush()
        session.add(SourceEntityIdentifier(
            source_id=source.id, entity_type="PLAYER", entity_id=player.id, identifier_kind="BWF_PROFILE_ID",
            identifier_value=profile["bwf_profile_id"], confidence="OFFICIAL_DIRECT", evidence_record_id=raw.id,
        ))
    else:
        player.full_name = profile["full_name"]
        player.first_name = profile["first_name"]
        player.last_name = profile["last_name"]
        player.country_code = profile["country_code"]
        player.country_name = profile["country_name"]
        player.date_of_birth = profile["date_of_birth"]
        player.profile_url = f"https://bwfbadminton.com/player/{profile['bwf_profile_id']}"
        player.identity_status = "CONFIRMED"
        player.last_identity_verified_at = utcnow()
    snapshot = session.scalar(select(PlayerProfileSnapshot).where(
        PlayerProfileSnapshot.source_id == source.id,
        PlayerProfileSnapshot.bwf_profile_id == profile["bwf_profile_id"],
        PlayerProfileSnapshot.content_hash == raw.content_hash,
    ))
    if snapshot is None:
        snapshot = PlayerProfileSnapshot(
            source_id=source.id, source_record_id=raw.id, bwf_profile_id=profile["bwf_profile_id"], source_url=response.url,
            retrieved_at=utcnow(), content_hash=raw.content_hash, profile_name=profile["full_name"], country_code=profile["country_code"],
            date_of_birth=profile["date_of_birth"], profile_type=profile["profile_type"], payload=profile["payload"], parser_version=PARSER_VERSION,
        )
        session.add(snapshot)
        session.flush()
    return player, snapshot


def decide_alias(
    alias: PlayerAlias,
    player: Player,
    snapshot: PlayerProfileSnapshot,
    exact_candidate_count: int,
    search_country_code: str | None = None,
) -> tuple[str, str, int, dict[str, Any], str]:
    alias_name = normalize_name(alias.alias_text)
    official_name = normalize_name(player.full_name)
    profile_bwf_nationality_code = first_present(as_mapping(snapshot.payload), "nationality")
    profile_bwf_nationality_code = str(profile_bwf_nationality_code).upper()[:8] if profile_bwf_nationality_code else None
    normalized_search_country_code = search_country_code.upper()[:8] if search_country_code else None
    evidence = {
        "alias_text": alias.alias_text, "normalized_alias": alias_name, "official_name": player.full_name,
        "official_profile_id": snapshot.bwf_profile_id,
        "official_profile_bwf_nationality_code": profile_bwf_nationality_code,
        "official_country_iso3_code": player.country_code,
        "exact_candidate_count": exact_candidate_count, "profile_snapshot_id": snapshot.id,
        "search_country_code": normalized_search_country_code,
    }
    if alias_name != official_name:
        return "UNRESOLVED", "NAME_MISMATCH", 0, evidence, "Official profile name does not exactly match the historical alias after normalisation."
    if normalized_search_country_code and profile_bwf_nationality_code and normalized_search_country_code != profile_bwf_nationality_code:
        return "CONFLICTED", "COUNTRY_MISMATCH", 20, evidence, "Official BWF search-country and official BWF profile nationality disagree; no identity link is allowed."
    if exact_candidate_count != 1:
        return "CONFLICTED", "MULTIPLE_CANDIDATES", 40, evidence, "More than one official profile matches the historical alias exactly."
    # Historical aliases do not reliably carry country; a unique exact official profile is a strong automated link,
    # but the decision record retains the full evidence and is still subject to later correction.
    return "CONFIRMED_AUTO", "UNIQUE_EXACT_NAME", 80, evidence, "One official BWF profile exactly matches the normalised historical alias and no competing exact profile was returned."


def apply_decision(session: Session, alias: PlayerAlias, player: Player, snapshot: PlayerProfileSnapshot, decision: tuple[str, str, int, dict[str, Any], str], settings: Settings) -> PlayerIdentityLink:
    status, decision_class, score, evidence, rationale = decision
    existing = session.scalar(select(PlayerIdentityLink).where(
        PlayerIdentityLink.alias_id == alias.id, PlayerIdentityLink.player_id == player.id,
        PlayerIdentityLink.resolver_version == RESOLVER_VERSION,
    ))
    if existing:
        if existing.decision_status == "CONFIRMED_AUTO" and settings.bwf_player_profiles_auto_confirm and not settings.bwf_player_profiles_dry_run:
            alias.player_id = player.id
            alias.resolution_status = "CONFIRMED"
            for member in session.scalars(select(ParticipantMember).where(ParticipantMember.source_alias_id == alias.id)).all():
                member.player_id = player.id
        return existing
    link = PlayerIdentityLink(alias_id=alias.id, player_id=player.id, profile_snapshot_id=snapshot.id, decision_status=status,
        decision_class=decision_class, score=score, resolver_version=RESOLVER_VERSION, evidence=evidence, rationale=rationale)
    session.add(link)
    if status == "CONFIRMED_AUTO" and settings.bwf_player_profiles_auto_confirm and not settings.bwf_player_profiles_dry_run:
        alias.player_id = player.id
        alias.resolution_status = "CONFIRMED"
        members = session.scalars(select(ParticipantMember).where(ParticipantMember.source_alias_id == alias.id)).all()
        for member in members:
            member.player_id = player.id
    elif status == "CONFLICTED":
        alias.resolution_status = "CONFLICTED"
        session.add(ReconciliationCase(case_type="PLAYER_IDENTITY_CONFLICT", status="OPEN", candidate_entity_type="PLAYER", candidate_entity_id=player.id, rationale=rationale))
    session.flush()
    return link


def run_full_queue(session: Session, settings: Settings | None = None, client: BWFPlayerProfileClient | None = None) -> dict[str, int]:
    settings = settings or get_settings()
    ensure_collection_allowed(settings)
    source = get_or_create_source(session, settings)
    batch = ImportBatch(batch_type="BWF_PLAYER_PROFILE_IDENTITY", status=BatchStatus.RUNNING.value, started_at=utcnow(), importer_version=RESOLVER_VERSION)
    session.add(batch)
    session.flush()
    created_client = client is None
    client = client or BWFPlayerProfileClient(settings)
    summary = {"selected": 0, "confirmed_auto": 0, "provisional": 0, "conflicted": 0, "unresolved": 0, "errors": 0}
    try:
        current_resolver_link_exists = select(PlayerIdentityLink.id).where(
            PlayerIdentityLink.alias_id == PlayerAlias.id,
            PlayerIdentityLink.resolver_version == RESOLVER_VERSION,
        ).exists()
        aliases = session.scalars(
            select(PlayerAlias)
            .where(PlayerAlias.player_id.is_(None), ~current_resolver_link_exists)
            .order_by(PlayerAlias.created_at)
            .limit(settings.bwf_player_profiles_batch_size)
        ).all()
        for alias in aliases:
            summary["selected"] += 1
            search = client.search(alias.alias_text)
            persist_raw(session, source, search)
            candidates = extract_candidates(search.payload)
            exact = [candidate for candidate in candidates if normalize_name(candidate.display_name) == normalize_name(alias.alias_text)]
            if not exact:
                summary["unresolved"] += 1
                continue
            # Inspect only exact candidates; the source request interval applies to every profile.
            resolved: list[tuple[Candidate, Player, PlayerProfileSnapshot]] = []
            for candidate in exact:
                profile_response = client.summary(candidate.bwf_profile_id)
                player, snapshot = upsert_canonical_profile(session, source, profile_response)
                resolved.append((candidate, player, snapshot))
            for candidate, player, snapshot in resolved:
                decision = decide_alias(alias, player, snapshot, len(resolved), candidate.country_code)
                status, *_ = decision
                apply_decision(session, alias, player, snapshot, decision, settings)
                if status == "CONFIRMED_AUTO":
                    summary["confirmed_auto"] += 1
                elif status == "CONFLICTED":
                    summary["conflicted"] += 1
                else:
                    summary["provisional"] += 1
        batch.status = BatchStatus.SUCCEEDED.value
        batch.completed_at = utcnow()
        batch.input_row_count = summary["selected"]
        batch.accepted_count = summary["confirmed_auto"] + summary["provisional"]
        batch.rejected_count = summary["conflicted"] + summary["unresolved"]
        return summary
    except SourceAccessStopped as exc:
        batch.status = BatchStatus.FAILED.value
        batch.error_summary = str(exc)
        batch.completed_at = utcnow()
        raise
    except Exception as exc:
        batch.status = BatchStatus.FAILED.value
        batch.error_summary = str(exc)
        batch.completed_at = utcnow()
        raise
    finally:
        if created_client:
            client.close()
""
