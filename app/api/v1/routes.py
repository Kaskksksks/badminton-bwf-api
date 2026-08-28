from __future__ import annotations

from datetime import datetime, timezone
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import and_, desc, func, or_, select
from sqlalchemy.orm import Session

from app.api.dependencies import require_admin
from app.db.base import get_db
from app.db.models import (
    Event,
    GameIntervalAssessment,
    GameStateObservation,
    HeadToHeadSnapshot,
    ImportBatch,
    OfficialDrawNode,
    OfficialDrawNodeReconciliation,
    OfficialDrawTopology,
    Match,
    MatchGame,
    Participant,
    Player,
    PlayerAlias,
    PlayerIdentityLink,
    ParticipantMember,
    ReconciliationCase,
    RecordLineage,
    RankingEntry,
    RankingSnapshot,
    Tournament,
)
from app.core.config import get_settings
from app.core.worker_safety import collection_slot
from app.ingestion.player_profiles.country_mismatch import (
    COUNTRY_MISMATCH_POLICY_VERSION,
    MANUAL_OVERRIDE_POLICY_VERSION,
    evaluate_country_mismatch_evidence,
)
from app.ingestion.calendar_draws.topology import (
    publish_topology_after_full_reconciliation,
    record_canonical_reconciliation,
    stage_topology_from_extracted_text,
)
from app.ingestion.rankings.service import diagnose_ranking_row_shape, synchronize_rankings
from app.ingestion.player_profiles.service import (
    NO_EXACT_CANDIDATE_CASE_TYPE,
    NO_RECENT_SENIOR_ACTIVITY_CASE_TYPE,
    NO_SENIOR_CONTEXT_CASE_TYPE,
    RECENT_SENIOR_ELIGIBLE_CASE_TYPE,
    RESOLVER_VERSION,
    context_summaries_for_aliases,
    context_summary_for_player,
    run_full_queue,
    run_local_classification_sweep,
)
from app.statistics.service import interval_coverage_summary, interval_metrics_for_participant

router = APIRouter(tags=["v1"])


class DrawParseRequest(BaseModel):
    discipline: str = Field(pattern="^(MS|WS|MD|WD|XD)$")
    source_content_hash: str = Field(min_length=32, max_length=128)
    extracted_text: str = Field(min_length=1, max_length=2_000_000)


class DrawReconcileRequest(BaseModel):
    match_id: str = Field(min_length=1, max_length=64)
    rationale: str = Field(min_length=1, max_length=4000)


class DrawPublishRequest(BaseModel):
    review_note: str = Field(min_length=1, max_length=4000)
DbSession = Annotated[Session, Depends(get_db)]


def meta(source: str = "PLATFORM") -> dict[str, Any]:
    return {"timestamp": datetime.now(timezone.utc).isoformat(), "source": source, "api_version": "v1"}


def page_payload(items: list[Any], page: int, page_size: int, total: int, source: str = "PLATFORM") -> dict[str, Any]:
    return {"data": items, "pagination": {"page": page, "page_size": page_size, "total": total}, "meta": meta(source)}


def _int_evidence_value(evidence: dict[str, Any], key: str) -> int | None:
    value = evidence.get(key)
    return value if isinstance(value, int) else None


def _country_mismatch_audit_rows(session: Session) -> list[dict[str, Any]]:
    """Audit stored country conflicts only; this makes no BWF request and no write."""
    links = session.scalars(
        select(PlayerIdentityLink)
        .join(PlayerAlias, PlayerAlias.id == PlayerIdentityLink.alias_id)
        .where(
            PlayerIdentityLink.decision_status == "CONFLICTED",
            PlayerIdentityLink.decision_class == "COUNTRY_MISMATCH",
            PlayerAlias.player_id.is_(None),
        )
        .order_by(desc(PlayerIdentityLink.decided_at), PlayerIdentityLink.id)
    ).all()
    aliases = session.scalars(
        select(PlayerAlias).where(PlayerAlias.id.in_({link.alias_id for link in links}))
    ).all() if links else []
    aliases_by_id = {alias.id: alias for alias in aliases}
    contexts = context_summaries_for_aliases(session, list(aliases_by_id))
    rows: list[dict[str, Any]] = []
    for link in links:
        alias = aliases_by_id.get(link.alias_id)
        evidence = link.evidence if isinstance(link.evidence, dict) else {}
        evaluation = evaluate_country_mismatch_evidence(evidence)
        context = contexts.get(link.alias_id)
        exact_candidate_count = _int_evidence_value(evidence, "exact_candidate_count")
        has_profile_evidence = bool(evidence.get("official_profile_id") and evidence.get("profile_snapshot_id"))
        disposition = evaluation.disposition
        blocker: str | None = None
        if alias is None:
            disposition = "REMAIN_CONFLICTED"
            blocker = "ALIAS_MISSING"
        elif alias.player_id is not None:
            disposition = "REMAIN_CONFLICTED"
            blocker = "ALIAS_ALREADY_LINKED"
        elif exact_candidate_count != 1:
            disposition = "REMAIN_CONFLICTED"
            blocker = "MULTIPLE_OR_NONUNIQUE_EXACT_CANDIDATES"
        elif not has_profile_evidence:
            disposition = "REMAIN_CONFLICTED"
            blocker = "INCOMPLETE_STORED_OFFICIAL_EVIDENCE"
        elif context is None or not context.eligible_for_profile_search:
            disposition = "REMAIN_CONFLICTED"
            blocker = "NOT_RECENT_SENIOR_ELIGIBLE"
        rows.append({
            "link_id": link.id,
            "alias_id": link.alias_id,
            "alias_text": alias.alias_text if alias else None,
            "player_id": link.player_id,
            "decision_status": link.decision_status,
            "decision_class": link.decision_class,
            "exact_candidate_count": exact_candidate_count,
            "stored_official_evidence_complete": has_profile_evidence,
            "activity_evidence": context.evidence() if context else None,
            "recent_senior_eligible": bool(context and context.eligible_for_profile_search),
            "proposed_disposition": disposition,
            "blocker": blocker,
            "country_evaluation": evaluation.as_dict(),
            "rationale": link.rationale,
            "evidence": evidence,
        })
    return rows


def _apply_country_mismatch_resolution(session: Session, row: dict[str, Any], *, actor: str) -> bool:
    """Create a new audited decision without mutating the original conflicted evidence."""
    disposition = row["proposed_disposition"]
    if disposition not in {"AUTO_EQUIVALENT_ELIGIBLE", "MANUAL_OVERRIDE_ELIGIBLE"}:
        return False
    alias = session.get(PlayerAlias, row["alias_id"])
    if alias is None or alias.player_id is not None:
        return False
    source_link = session.get(PlayerIdentityLink, row["link_id"])
    if source_link is None:
        return False
    resolver_version = (
        COUNTRY_MISMATCH_POLICY_VERSION
        if disposition == "AUTO_EQUIVALENT_ELIGIBLE"
        else MANUAL_OVERRIDE_POLICY_VERSION
    )
    existing = session.scalar(select(PlayerIdentityLink).where(
        PlayerIdentityLink.alias_id == alias.id,
        PlayerIdentityLink.player_id == source_link.player_id,
        PlayerIdentityLink.resolver_version == resolver_version,
    ))
    if existing:
        return False
    decision_status = (
        "CONFIRMED_AUTO_EQUIVALENT"
        if disposition == "AUTO_EQUIVALENT_ELIGIBLE"
        else "CONFIRMED_MANUAL_OVERRIDE"
    )
    decision_class = (
        "DOCUMENTED_COUNTRY_EQUIVALENCE"
        if disposition == "AUTO_EQUIVALENT_ELIGIBLE"
        else "USER_DIRECTED_COUNTRY_OVERRIDE"
    )
    evidence = {
        **(source_link.evidence if isinstance(source_link.evidence, dict) else {}),
        "country_mismatch_review": {
            "source_conflicted_link_id": source_link.id,
            "proposed_disposition": disposition,
            "policy_version": row["country_evaluation"]["policy_version"],
            "reason_code": row["country_evaluation"]["reason_code"],
            "manual_override_pair": row["country_evaluation"]["manual_override_pair"],
        },
    }
    resolved_link = PlayerIdentityLink(
        alias_id=alias.id,
        player_id=source_link.player_id,
        profile_snapshot_id=source_link.profile_snapshot_id,
        decision_status=decision_status,
        decision_class=decision_class,
        score=80 if disposition == "AUTO_EQUIVALENT_ELIGIBLE" else 60,
        resolver_version=resolver_version,
        evidence=evidence,
        rationale=(
            "Stored official country codes are a documented ISO/BWF/IOC equivalence."
            if disposition == "AUTO_EQUIVALENT_ELIGIBLE"
            else "User-directed country-designation override applied to stored official evidence."
        ),
        decided_by=actor,
        reviewed_at=datetime.now(timezone.utc) if disposition == "MANUAL_OVERRIDE_ELIGIBLE" else None,
        reviewed_by=actor if disposition == "MANUAL_OVERRIDE_ELIGIBLE" else None,
    )
    session.add(resolved_link)
    alias.player_id = source_link.player_id
    alias.resolution_status = "CONFIRMED"
    for member in session.scalars(select(ParticipantMember).where(ParticipantMember.source_alias_id == alias.id)).all():
        member.player_id = source_link.player_id
    case = session.scalar(select(ReconciliationCase).where(
        ReconciliationCase.case_type == "PLAYER_IDENTITY_COUNTRY_MISMATCH_RESOLUTION",
        ReconciliationCase.candidate_entity_type == "PLAYER_ALIAS",
        ReconciliationCase.candidate_entity_id == alias.id,
        ReconciliationCase.status == "RESOLVED",
    ))
    if case is None:
        session.add(ReconciliationCase(
            case_type="PLAYER_IDENTITY_COUNTRY_MISMATCH_RESOLUTION",
            status="RESOLVED",
            candidate_entity_type="PLAYER_ALIAS",
            candidate_entity_id=alias.id,
            rationale=resolved_link.rationale,
            resolved_at=datetime.now(timezone.utc),
            resolved_by=actor,
        ))
    session.flush()
    return True


def serialize_tournament(value: Tournament) -> dict[str, Any]:
    return {
        "id": value.id,
        "name": value.name,
        "source_name_raw": value.source_name_raw,
        "location_raw": value.location_raw,
        "start_date": value.start_date.isoformat() if value.start_date else None,
        "end_date": value.end_date.isoformat() if value.end_date else None,
        "status": value.status,
        "source_url": value.source_url,
    }


def serialize_match(value: Match) -> dict[str, Any]:
    return {
        "id": value.id,
        "match_date": value.match_date.isoformat() if value.match_date else None,
        "tournament_id": value.tournament_id,
        "event_id": value.event_id,
        "round": value.round_raw,
        "court": {"code": value.court_code, "name": value.court_name},
        "status": value.status,
        "participant_1_id": value.participant_1_id,
        "participant_2_id": value.participant_2_id,
        "winner_participant_id": value.winner_participant_id,
        "score_raw": value.score_raw,
        "score_parse_status": value.score_parse_status,
        "score_validation_status": value.score_validation_status,
        "completion_basis": value.completion_basis,
        "source_completeness": value.source_completeness,
        "historical_seed": value.historical_seed_flag,
    }


def serialize_game(value: MatchGame) -> dict[str, Any]:
    return {
        "id": value.id,
        "game_number": value.game_number,
        "participant_1_score": value.participant_1_score,
        "participant_2_score": value.participant_2_score,
        "winner_participant_id": value.winner_participant_id,
        "status": value.status,
        "parse_confidence": value.parse_confidence,
    }


def require_match(session: Session, match_id: str) -> Match:
    value = session.get(Match, match_id)
    if not value:
        raise HTTPException(status_code=404, detail="Match not found")
    return value


@router.get("/players")
def list_players(
    session: DbSession,
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
) -> dict[str, Any]:
    total = len(session.scalars(select(Player)).all())
    values = session.scalars(select(Player).order_by(Player.full_name).offset((page - 1) * page_size).limit(page_size)).all()
    return page_payload([
        {"id": item.id, "full_name": item.full_name, "country_code": item.country_code, "identity_status": item.identity_status}
        for item in values
    ], page, page_size, total, "BWF_LIVE_AND_RESOLVED_IDENTITIES")


@router.get("/players/{player_id}")
def get_player(player_id: str, session: DbSession) -> dict[str, Any]:
    value = session.get(Player, player_id)
    if not value:
        raise HTTPException(status_code=404, detail="Player not found")
    activity = context_summary_for_player(session, value)
    return {"data": {"id": value.id, "full_name": value.full_name, "country_code": value.country_code, "profile_url": value.profile_url, "identity_status": value.identity_status, "activity_status": activity.activity_status, "trusted_statistics_eligible": activity.eligible_for_profile_search, "activity_evidence": activity.evidence()}, "meta": meta("BWF_LIVE_AND_RESOLVED_IDENTITIES")}


@router.get("/players/{player_id}/matches")
def get_player_matches(player_id: str, session: DbSession) -> dict[str, Any]:
    player = session.get(Player, player_id)
    if not player:
        raise HTTPException(status_code=404, detail="Player not found")
    participant_ids = session.scalars(
        select(ParticipantMember.participant_id).where(ParticipantMember.player_id == player_id)
    ).all()
    if not participant_ids:
        return {"data": [], "meta": {**meta("BWF_LIVE_AND_RESOLVED_IDENTITIES"), "notice": "No confirmed participant linkage is stored for this player."}}
    values = session.scalars(
        select(Match).where(or_(Match.participant_1_id.in_(participant_ids), Match.participant_2_id.in_(participant_ids)))
        .order_by(desc(Match.match_date), Match.id)
        .limit(500)
    ).all()
    return {"data": [serialize_match(value) for value in values], "meta": meta("BWF_LIVE_AND_RESOLVED_IDENTITIES")}


@router.get("/players/{player_id}/statistics")
def get_player_statistics(player_id: str, session: DbSession) -> dict[str, Any]:
    player = session.get(Player, player_id)
    if not player:
        raise HTTPException(status_code=404, detail="Player not found")
    activity = context_summary_for_player(session, player)
    if not activity.eligible_for_profile_search:
        return {"data": {"player_id": player_id, "statistics": [], "coverage": interval_coverage_summary(session), "activity_status": activity.activity_status, "trusted_statistics_eligible": False, "activity_evidence": activity.evidence()}, "meta": {**meta(), "notice": "Trusted player statistics are withheld until confirmed identity has a dated COMPLETED or RETIRED senior, non-Para official match within the prior 52 weeks."}}
    participant_ids = sorted(set(session.scalars(
        select(ParticipantMember.participant_id).where(ParticipantMember.player_id == player_id)
    ).all()))
    statistics = [
        interval_metrics_for_participant(session, participant_id)
        for participant_id in participant_ids
    ]
    published_statistics = [item for item in statistics if item["eligible_games"] > 0]
    notice = (
        "Statistics include only stored, coverage-eligible eleven-point interval assessments; missing observations are not estimated."
        if published_statistics
        else "No coverage-eligible eleven-point interval assessments are stored for this confirmed active player."
    )
    return {"data": {"player_id": player_id, "statistics": published_statistics, "coverage": interval_coverage_summary(session), "activity_status": activity.activity_status, "trusted_statistics_eligible": True, "activity_evidence": activity.evidence()}, "meta": {**meta("BWF_LIVE_DERIVED"), "notice": notice}}


@router.get("/rankings")
def get_rankings(
    session: DbSession,
    ranking_system: str = Query("WORLD", pattern="^(WORLD|WORLD_TOUR|WORLD_JUNIOR)$"),
    discipline: str = Query("MS", pattern="^(MS|WS|MD|WD|XD)$"),
    effective_date: str | None = None,
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
) -> dict[str, Any]:
    """Read a stored official ranking snapshot; this endpoint never calls BWF."""
    query = select(RankingSnapshot).where(
        RankingSnapshot.ranking_system == ranking_system,
        RankingSnapshot.discipline == discipline,
        RankingSnapshot.snapshot_status == "COMPLETE",
    )
    if effective_date:
        query = query.where(RankingSnapshot.effective_date == effective_date)
    snapshot = session.scalar(query.order_by(desc(RankingSnapshot.effective_date), desc(RankingSnapshot.retrieved_at)))
    if not snapshot:
        return {
            "data": [],
            "pagination": {"page": page, "page_size": page_size, "total": 0},
            "meta": {
                **meta("BWF_OFFICIAL_RANKINGS"),
                "ranking_system": ranking_system,
                "discipline": discipline,
                "status": "NOT_YET_INGESTED",
            },
        }
    entry_query = select(RankingEntry).where(RankingEntry.snapshot_id == snapshot.id)
    total = len(session.scalars(entry_query).all())
    entries = session.scalars(
        entry_query.order_by(RankingEntry.ranking_position, RankingEntry.subject_display_name)
        .offset((page - 1) * page_size)
        .limit(page_size)
    ).all()
    return {
        "data": [
            {
                "ranking_position": item.ranking_position,
                "points": item.points,
                "tournament_count": item.tournament_count,
                "rank_change": item.rank_change,
                "subject_kind": item.subject_kind,
                "subject_display_name": item.subject_display_name,
                "official_subject_id": item.official_subject_id,
                "country_code": item.country_code,
                "platform_player_id": item.platform_player_id,
                "identity_status": item.identity_status,
            }
            for item in entries
        ],
        "pagination": {"page": page, "page_size": page_size, "total": total},
        "meta": {
            **meta("BWF_OFFICIAL_RANKINGS"),
            "ranking_system": snapshot.ranking_system,
            "population": snapshot.population,
            "discipline": snapshot.discipline,
            "effective_date": snapshot.effective_date.isoformat(),
            "published_week": snapshot.published_week,
            "retrieved_at": snapshot.retrieved_at.isoformat(),
            "source_url": snapshot.source_url,
            "content_hash": snapshot.content_hash,
            "snapshot_status": snapshot.snapshot_status,
            "issue_summary": snapshot.issue_summary,
        },
    }


@router.get("/admin/identity/coverage", dependencies=[Depends(require_admin)])
def identity_coverage(session: DbSession) -> dict[str, Any]:
    aliases = session.scalars(select(PlayerAlias)).all()
    links = session.scalars(select(PlayerIdentityLink)).all()
    terminal_no_exact_alias_ids = set(session.scalars(select(ReconciliationCase.candidate_entity_id).where(
        ReconciliationCase.case_type == NO_EXACT_CANDIDATE_CASE_TYPE,
        ReconciliationCase.candidate_entity_type == "PLAYER_ALIAS",
        ReconciliationCase.status == "OPEN",
    )).all())
    source_error_alias_ids = set(session.scalars(select(ReconciliationCase.candidate_entity_id).where(
        ReconciliationCase.case_type == "PLAYER_IDENTITY_SOURCE_ERROR",
        ReconciliationCase.candidate_entity_type == "PLAYER_ALIAS",
        ReconciliationCase.status == "OPEN",
    )).all())
    no_senior_context_alias_ids = set(session.scalars(select(ReconciliationCase.candidate_entity_id).where(
        ReconciliationCase.case_type == NO_SENIOR_CONTEXT_CASE_TYPE,
        ReconciliationCase.candidate_entity_type == "PLAYER_ALIAS",
        ReconciliationCase.status == "OPEN",
    )).all())
    no_recent_senior_activity_alias_ids = set(session.scalars(select(ReconciliationCase.candidate_entity_id).where(
        ReconciliationCase.case_type == NO_RECENT_SENIOR_ACTIVITY_CASE_TYPE,
        ReconciliationCase.candidate_entity_type == "PLAYER_ALIAS",
        ReconciliationCase.status == "OPEN",
    )).all())
    recent_senior_eligible_alias_ids = set(session.scalars(select(ReconciliationCase.candidate_entity_id).where(
        ReconciliationCase.case_type == RECENT_SENIOR_ELIGIBLE_CASE_TYPE,
        ReconciliationCase.candidate_entity_type == "PLAYER_ALIAS",
        ReconciliationCase.status == "RESOLVED",
    )).all())
    resolver_link_alias_ids = set(session.scalars(select(PlayerIdentityLink.alias_id).where(
        PlayerIdentityLink.resolver_version == RESOLVER_VERSION,
    )).all())
    eligible_queue_remaining = sum(
        item.player_id is None
        and item.id not in resolver_link_alias_ids
        and item.id not in terminal_no_exact_alias_ids
        and item.id not in source_error_alias_ids
        and item.id not in no_senior_context_alias_ids
        and item.id not in no_recent_senior_activity_alias_ids
        for item in aliases
    )
    local_classification_remaining = sum(
        item.player_id is None
        and item.id not in resolver_link_alias_ids
        and item.id not in terminal_no_exact_alias_ids
        and item.id not in source_error_alias_ids
        and item.id not in no_senior_context_alias_ids
        and item.id not in no_recent_senior_activity_alias_ids
        and item.id not in recent_senior_eligible_alias_ids
        for item in aliases
    )
    return {
        "data": {
            "aliases_total": len(aliases),
            "aliases_confirmed": sum(item.player_id is not None and item.resolution_status == "CONFIRMED" for item in aliases),
            "aliases_unresolved": sum(item.player_id is None and item.resolution_status == "UNRESOLVED" for item in aliases),
            "aliases_conflicted": sum(item.resolution_status == "CONFLICTED" for item in aliases),
            "automated_links": sum(item.decision_status == "CONFIRMED_AUTO" for item in links),
            "country_equivalent_links": sum(item.decision_status == "CONFIRMED_AUTO_EQUIVALENT" for item in links),
            "country_manual_override_links": sum(item.decision_status == "CONFIRMED_MANUAL_OVERRIDE" for item in links),
            "provisional_links": sum(item.decision_status == "PROVISIONAL_AUTO" for item in links),
            "rejected_links": sum(item.decision_status == "REJECTED_MANUAL" for item in links),
            "aliases_no_exact_candidate": len(terminal_no_exact_alias_ids),
            "aliases_source_error_quarantined": len(source_error_alias_ids),
            "aliases_no_senior_context": len(no_senior_context_alias_ids),
            "aliases_no_recent_senior_activity": len(no_recent_senior_activity_alias_ids),
            "aliases_recent_senior_eligible": len(recent_senior_eligible_alias_ids),
            "local_classification_remaining": local_classification_remaining,
            "eligible_queue_remaining": eligible_queue_remaining,
            "queue_complete": eligible_queue_remaining == 0,
            "model_safe_identity_status": "CONFIRMED_ONLY",
            "model_safe_activity_status": "RECENT_SENIOR_PARTICIPATION_REQUIRED",
        },
        "meta": {**meta("BWF_OFFICIAL_PLAYER_PROFILES"), "notice": "Trusted player statistics and models require confirmed identity plus recent senior official participation. Queue completion means every alias is confirmed, conflicted, no-exact-candidate, source-error quarantined, or excluded from automatic processing because it lacks a recoverable senior source context or recent senior official participation."},
    }


@router.get("/admin/identity/review-queue", dependencies=[Depends(require_admin)])
def identity_review_queue(session: DbSession, page: int = Query(1, ge=1), page_size: int = Query(50, ge=1, le=200)) -> dict[str, Any]:
    query = (
        select(PlayerIdentityLink)
        .join(PlayerAlias, PlayerAlias.id == PlayerIdentityLink.alias_id)
        .where(
            PlayerIdentityLink.decision_status.in_(("CONFLICTED", "PROVISIONAL_AUTO")),
            PlayerAlias.player_id.is_(None),
        )
    )
    total = len(session.scalars(query).all())
    rows = session.scalars(query.order_by(desc(PlayerIdentityLink.decided_at)).offset((page - 1) * page_size).limit(page_size)).all()
    return page_payload([
        {"link_id": row.id, "alias_id": row.alias_id, "player_id": row.player_id, "status": row.decision_status,
         "decision_class": row.decision_class, "score": row.score, "rationale": row.rationale, "evidence": row.evidence}
        for row in rows
    ], page, page_size, total, "BWF_OFFICIAL_PLAYER_PROFILES")


@router.get("/admin/identity/country-mismatch-audit", dependencies=[Depends(require_admin)])
def country_mismatch_audit(
    session: DbSession,
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
) -> dict[str, Any]:
    """Return all stored country mismatch dispositions without a source request or write."""
    rows = _country_mismatch_audit_rows(session)
    counts = {
        disposition: sum(item["proposed_disposition"] == disposition for item in rows)
        for disposition in ("AUTO_EQUIVALENT_ELIGIBLE", "MANUAL_OVERRIDE_ELIGIBLE", "REMAIN_CONFLICTED")
    }
    start = (page - 1) * page_size
    return {
        "data": rows[start:start + page_size],
        "pagination": {"page": page, "page_size": page_size, "total": len(rows)},
        "summary": {"counts": counts, "policy_version": COUNTRY_MISMATCH_POLICY_VERSION},
        "meta": {**meta("LOCAL_STORED_IDENTITY_EVIDENCE"), "notice": "Read-only audit: no official BWF request was made and no identity link was changed."},
    }


@router.post("/admin/identity/country-mismatch/apply", dependencies=[Depends(require_admin)])
def apply_country_mismatch_resolutions(
    session: DbSession,
    action: str = Query(..., pattern="^APPLY$"),
) -> dict[str, Any]:
    """Apply only pre-validated mismatch dispositions; never invokes the general queue."""
    _ = action
    with collection_slot("identity_country_mismatch_apply") as acquired:
        if not acquired:
            raise HTTPException(status_code=409, detail="Live polling or another identity operation is in progress; retry after it finishes.")
        rows = _country_mismatch_audit_rows(session)
        applied_auto_equivalent = 0
        applied_manual_override = 0
        for row in rows:
            if _apply_country_mismatch_resolution(session, row, actor="ADMIN_COUNTRY_MISMATCH_POLICY"):
                if row["proposed_disposition"] == "AUTO_EQUIVALENT_ELIGIBLE":
                    applied_auto_equivalent += 1
                else:
                    applied_manual_override += 1
        session.commit()
    return {
        "data": {
            "applied_auto_equivalent": applied_auto_equivalent,
            "applied_manual_override": applied_manual_override,
            "skipped": len(rows) - applied_auto_equivalent - applied_manual_override,
        },
        "meta": {**meta("LOCAL_STORED_IDENTITY_EVIDENCE"), "notice": "No official BWF request was made. Original conflicted link evidence was retained and new decisions are auditable."},
    }


@router.post("/admin/identity/run", dependencies=[Depends(require_admin)])
def run_identity_batch(session: DbSession) -> dict[str, Any]:
    """Start one explicit batch only when the live collector is idle."""
    with collection_slot("identity_batch") as acquired:
        if not acquired:
            raise HTTPException(status_code=409, detail="Live polling is in progress; retry the manual identity batch after it finishes.")
        summary = run_full_queue(session, get_settings())
        session.commit()
    return {"data": summary, "meta": meta("BWF_OFFICIAL_PLAYER_PROFILES")}


@router.post("/admin/identity/classify-local", dependencies=[Depends(require_admin)])
def run_local_identity_classification(session: DbSession, batch_size: int = Query(500, ge=1, le=500)) -> dict[str, Any]:
    """Classify one bounded local slice without instantiating an official BWF client."""
    with collection_slot("identity_local_classification") as acquired:
        if not acquired:
            raise HTTPException(status_code=409, detail="Live polling or an identity batch is in progress; retry local classification after it finishes.")
        summary = run_local_classification_sweep(session, batch_size=batch_size)
        session.commit()
    return {"data": summary, "meta": {**meta("LOCAL_EXISTING_SOURCE_CONTEXT"), "notice": "No official BWF requests were made by this local classification operation."}}


@router.post("/admin/identity/links/{link_id}/review", dependencies=[Depends(require_admin)])
def review_identity_link(link_id: str, session: DbSession, action: str = Query(..., pattern="^(ACCEPT|REJECT)$")) -> dict[str, Any]:
    link = session.get(PlayerIdentityLink, link_id)
    if not link:
        raise HTTPException(status_code=404, detail="Identity link not found")
    alias = session.get(PlayerAlias, link.alias_id)
    if not alias:
        raise HTTPException(status_code=409, detail="Identity alias no longer exists")
    if action == "ACCEPT":
        alias.player_id = link.player_id
        alias.resolution_status = "CONFIRMED"
        link.decision_status = "ACCEPTED_MANUAL"
        for member in session.scalars(select(ParticipantMember).where(ParticipantMember.source_alias_id == alias.id)).all():
            member.player_id = link.player_id
    else:
        link.decision_status = "REJECTED_MANUAL"
        link.decision_class = "NEGATIVE_EVIDENCE"
        alias.resolution_status = "CONFLICTED"
    link.reviewed_at = datetime.now(timezone.utc)
    link.reviewed_by = "ADMIN_API"
    session.commit()
    return {"data": {"link_id": link.id, "decision_status": link.decision_status}, "meta": meta("BWF_OFFICIAL_PLAYER_PROFILES")}


@router.post("/admin/rankings/run", dependencies=[Depends(require_admin)])
def run_rankings_now(session: DbSession) -> dict[str, Any]:
    """Run one explicitly authorised ranking batch; never fetches during a public read."""
    with collection_slot("rankings_batch") as acquired:
        if not acquired:
            raise HTTPException(status_code=409, detail="Another collection operation is in progress; retry the ranking batch later.")
        try:
            summary = synchronize_rankings(session, settings=get_settings())
            session.commit()
        except RuntimeError as exc:
            session.rollback()
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        except Exception:
            session.rollback()
            raise
    return {"data": summary, "meta": meta("BWF_OFFICIAL_RANKINGS")}


@router.get("/admin/rankings/diagnostic", dependencies=[Depends(require_admin)])
def diagnose_rankings_now() -> dict[str, Any]:
    """Inspect key-only shape from one authorized senior ranking response without persisting it."""
    with collection_slot("rankings_diagnostic") as acquired:
        if not acquired:
            raise HTTPException(status_code=409, detail="Another collection operation is in progress; retry the ranking diagnostic later.")
        summary = diagnose_ranking_row_shape(settings=get_settings())
    return {"data": summary, "meta": meta("BWF_OFFICIAL_RANKINGS")}


@router.post("/admin/modeling/run", dependencies=[Depends(require_admin)])
def run_modeling_now(session: DbSession) -> dict[str, Any]:
    """Train/evaluate and publish only evidence-complete model outputs."""
    from app.modeling.service import run_model_pipeline

    with collection_slot("model_publication") as acquired:
        if not acquired:
            raise HTTPException(status_code=409, detail="Another collection operation is in progress; retry model publication later.")
        summary = run_model_pipeline(session, settings=get_settings())
        session.commit()
    return {"data": summary, "meta": meta("PLATFORM_MODEL")}


@router.post("/admin/draws/documents/{document_id}/collect-and-parse", dependencies=[Depends(require_admin)])
def collect_and_parse_draw_document(document_id: str, session: DbSession) -> dict[str, Any]:
    """Re-fetch the exact captured PDF, verify its hash, and stage all parseable disciplines."""
    from app.ingestion.calendar_draws.client import BWFCorporateCalendarClient
    from app.ingestion.calendar_draws.service import parse_captured_draw_document

    settings = get_settings()
    if settings.bwf_calendar_permission_required and not settings.bwf_calendar_permission_reference:
        raise HTTPException(status_code=409, detail="BWF Corporate calendar permission reference is not configured")
    with collection_slot("draw_reparse") as acquired:
        if not acquired:
            raise HTTPException(status_code=409, detail="Another collection operation is in progress; retry draw parsing later.")
        client = BWFCorporateCalendarClient(settings)
        try:
            result = parse_captured_draw_document(session, document_id=document_id, client=client, settings=settings)
            session.commit()
        except ValueError as exc:
            session.rollback()
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        finally:
            client.close()
    return {"data": result, "meta": meta("BWF_CORPORATE_CALENDAR")}


@router.post("/admin/draws/documents/{document_id}/parse", dependencies=[Depends(require_admin)])
def parse_draw_document(document_id: str, payload: DrawParseRequest, session: DbSession) -> dict[str, Any]:
    """Stage parser output from the exact captured PDF hash for later reconciliation."""
    topology = stage_topology_from_extracted_text(
        session,
        document_id=document_id,
        discipline=payload.discipline,
        source_content_hash=payload.source_content_hash,
        extracted_text=payload.extracted_text,
    )
    session.commit()
    return {"data": {"topology_id": topology.id, "topology_status": topology.topology_status}, "meta": meta("BWF_CORPORATE_CALENDAR")}


@router.get("/admin/draws/topologies/{topology_id}", dependencies=[Depends(require_admin)])
def inspect_draw_topology(topology_id: str, session: DbSession) -> dict[str, Any]:
    topology = session.get(OfficialDrawTopology, topology_id)
    if topology is None:
        raise HTTPException(status_code=404, detail="Official draw topology not found")
    nodes = session.scalars(select(OfficialDrawNode).where(OfficialDrawNode.topology_id == topology_id).order_by(OfficialDrawNode.display_order)).all()
    node_ids = [node.id for node in nodes]
    reconciliations = session.scalars(select(OfficialDrawNodeReconciliation).where(OfficialDrawNodeReconciliation.node_id.in_(node_ids))).all() if node_ids else []
    by_node = {item.node_id: item for item in reconciliations}
    return {"data": {"topology_id": topology.id, "document_id": topology.document_id, "discipline": topology.discipline, "topology_status": topology.topology_status, "nodes": [{"node_id": node.id, "source_node_key": node.source_node_key, "round_label": node.round_label, "display_order": node.display_order, "participant_1_label": node.participant_1_label, "participant_2_label": node.participant_2_label, "reconciliation": ({"reconciliation_id": by_node[node.id].id, "match_id": by_node[node.id].match_id, "status": by_node[node.id].reconciliation_status, "rationale": by_node[node.id].rationale} if node.id in by_node else None)} for node in nodes]}, "meta": meta("REVIEWED_DRAW_RECONCILIATION")}


@router.post("/admin/draws/nodes/{node_id}/reconcile", dependencies=[Depends(require_admin)])
def reconcile_draw_node(node_id: str, payload: DrawReconcileRequest, session: DbSession) -> dict[str, Any]:
    """Store an explicit reviewer-confirmed source-node to canonical-match link."""
    try:
        record = record_canonical_reconciliation(session, node_id=node_id, match_id=payload.match_id, rationale=payload.rationale)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    session.commit()
    return {"data": {"reconciliation_id": record.id, "status": record.reconciliation_status}, "meta": meta("REVIEWED_DRAW_RECONCILIATION")}


@router.post("/admin/draws/topologies/{topology_id}/publish", dependencies=[Depends(require_admin)])
def publish_draw_topology(topology_id: str, payload: DrawPublishRequest, session: DbSession) -> dict[str, Any]:
    """Publish a topology only after every extracted node has been reconciled."""
    try:
        topology = publish_topology_after_full_reconciliation(session, topology_id=topology_id, review_note=payload.review_note)
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    session.commit()
    return {"data": {"topology_id": topology.id, "topology_status": topology.topology_status}, "meta": meta("REVIEWED_DRAW_RECONCILIATION")}


@router.get("/tournaments")
def list_tournaments(
    session: DbSession,
    status: str | None = None,
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
) -> dict[str, Any]:
    query = select(Tournament)
    if status:
        query = query.where(Tournament.status == status)
    values = session.scalars(query.order_by(desc(Tournament.end_date)).offset((page - 1) * page_size).limit(page_size)).all()
    total = len(session.scalars(query).all())
    return page_payload([serialize_tournament(value) for value in values], page, page_size, total)


@router.get("/tournaments/{tournament_id}")
def get_tournament(tournament_id: str, session: DbSession) -> dict[str, Any]:
    value = session.get(Tournament, tournament_id)
    if not value:
        raise HTTPException(status_code=404, detail="Tournament not found")
    return {"data": serialize_tournament(value), "meta": meta()}


@router.get("/tournaments/{tournament_id}/matches")
def get_tournament_matches(tournament_id: str, session: DbSession) -> dict[str, Any]:
    values = session.scalars(select(Match).where(Match.tournament_id == tournament_id).order_by(Match.match_date)).all()
    return {"data": [serialize_match(value) for value in values], "meta": meta()}


@router.get("/matches")
def list_matches(
    session: DbSession,
    status: str | None = None,
    tournament_id: str | None = None,
    event_id: str | None = None,
    from_date: str | None = None,
    to_date: str | None = None,
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
) -> dict[str, Any]:
    query = select(Match)
    if status:
        query = query.where(Match.status == status)
    if tournament_id:
        query = query.where(Match.tournament_id == tournament_id)
    if event_id:
        query = query.where(Match.event_id == event_id)
    if from_date:
        query = query.where(Match.match_date >= from_date)
    if to_date:
        query = query.where(Match.match_date <= to_date)
    total = session.scalar(select(func.count()).select_from(query.subquery())) or 0
    values = session.scalars(query.order_by(desc(Match.match_date), Match.id).offset((page - 1) * page_size).limit(page_size)).all()
    return page_payload([serialize_match(value) for value in values], page, page_size, total)


@router.get("/matches/{match_id}")
def get_match(match_id: str, session: DbSession) -> dict[str, Any]:
    value = require_match(session, match_id)
    lineage = session.scalars(select(RecordLineage).where(RecordLineage.entity_type == "MATCH", RecordLineage.entity_id == match_id)).all()
    return {"data": {**serialize_match(value), "provenance": {"lineage_count": len(lineage)}}, "meta": meta()}


@router.get("/matches/{match_id}/games")
def get_match_games(match_id: str, session: DbSession) -> dict[str, Any]:
    require_match(session, match_id)
    values = session.scalars(select(MatchGame).where(MatchGame.match_id == match_id).order_by(MatchGame.game_number)).all()
    return {"data": [serialize_game(value) for value in values], "meta": meta()}


@router.get("/matches/{match_id}/live")
def get_match_live(match_id: str, session: DbSession) -> dict[str, Any]:
    value = require_match(session, match_id)
    states = session.scalars(select(GameStateObservation).where(GameStateObservation.match_id == match_id).order_by(desc(GameStateObservation.observed_at))).all()
    return {"data": {"match": serialize_match(value), "latest_states": [serialize_state(item) for item in states[:3]]}, "meta": meta("BWF_LIVE" if states else "PLATFORM")}


def serialize_state(value: GameStateObservation) -> dict[str, Any]:
    return {
        "id": value.id,
        "game_number": value.game_number,
        "participant_1_score": value.participant_1_score,
        "participant_2_score": value.participant_2_score,
        "observed_at": value.observed_at.isoformat(),
        "source_observed_at": value.source_observed_at.isoformat() if value.source_observed_at else None,
        "match_status": value.match_status,
        "source_precision": "SOURCE_TIME" if value.source_observed_at else "COLLECTION_TIME",
    }


@router.get("/matches/{match_id}/snapshots")
def get_match_snapshots(match_id: str, session: DbSession) -> dict[str, Any]:
    require_match(session, match_id)
    values = session.scalars(select(GameStateObservation).where(GameStateObservation.match_id == match_id).order_by(GameStateObservation.observed_at)).all()
    return {"data": [serialize_state(value) for value in values], "meta": meta("BWF_LIVE")}


@router.get("/matches/{match_id}/games/{game_number}/states")
def get_game_states(match_id: str, game_number: int, session: DbSession) -> dict[str, Any]:
    require_match(session, match_id)
    values = session.scalars(select(GameStateObservation).where(GameStateObservation.match_id == match_id, GameStateObservation.game_number == game_number).order_by(GameStateObservation.observed_at)).all()
    return {"data": [serialize_state(value) for value in values], "meta": meta("BWF_LIVE")}


@router.get("/matches/{match_id}/games/{game_number}/intervals")
def get_game_intervals(match_id: str, game_number: int, session: DbSession) -> dict[str, Any]:
    game = session.scalar(select(MatchGame).where(MatchGame.match_id == match_id, MatchGame.game_number == game_number))
    if not game:
        raise HTTPException(status_code=404, detail="Game not found")
    values = session.scalars(select(GameIntervalAssessment).where(GameIntervalAssessment.game_id == game.id)).all()
    return {"data": [{
        "interval_type": value.interval_type,
        "interval_player_participant_id": value.interval_player_participant_id,
        "score": {"participant_1": value.participant_1_score, "participant_2": value.participant_2_score},
        "interval_observed_at": value.interval_observed_at.isoformat() if value.interval_observed_at else None,
        "interval_source_at": value.interval_source_at.isoformat() if value.interval_source_at else None,
        "interval_exact": value.interval_exact,
        "detection_method": value.detection_method,
        "confidence": value.confidence,
        "derivation_version": value.derivation_version,
    } for value in values], "meta": meta("BWF_LIVE_DERIVED")}


@router.get("/live/matches")
def list_live_matches(session: DbSession) -> dict[str, Any]:
    values = session.scalars(select(Match).where(Match.status == "LIVE").order_by(desc(Match.updated_at))).all()
    return {"data": [serialize_match(value) for value in values], "meta": meta("BWF_LIVE")}


@router.get("/events/{event_id}")
def get_event(event_id: str, session: DbSession) -> dict[str, Any]:
    value = session.get(Event, event_id)
    if not value:
        raise HTTPException(status_code=404, detail="Event not found")
    return {"data": {"id": value.id, "tournament_id": value.tournament_id, "event_type": value.event_type, "category": value.category}, "meta": meta()}


@router.get("/head-to-head/{participant_a}/{participant_b}")
def head_to_head(participant_a: str, participant_b: str, session: DbSession) -> dict[str, Any]:
    a, b = sorted((participant_a, participant_b))
    snapshot = session.scalar(
        select(HeadToHeadSnapshot)
        .where(
            HeadToHeadSnapshot.participant_a_id == a,
            HeadToHeadSnapshot.participant_b_id == b,
            HeadToHeadSnapshot.summary_status == "VALIDATED",
        )
        .order_by(desc(HeadToHeadSnapshot.input_cutoff))
    )
    if snapshot:
        wins = {
            participant_a: snapshot.participant_a_wins if participant_a == a else snapshot.participant_b_wins,
            participant_b: snapshot.participant_b_wins if participant_b == b else snapshot.participant_a_wins,
        }
        return {"data": {"participant_a": participant_a, "participant_b": participant_b, "meetings": snapshot.eligible_meetings, "wins": wins, "input_cutoff": snapshot.input_cutoff.isoformat(), "snapshot_status": snapshot.summary_status, "evidence": snapshot.evidence}, "meta": meta("PLATFORM_MODEL")}
    values = session.scalars(
        select(Match).where(
            or_(
                and_(Match.participant_1_id == participant_a, Match.participant_2_id == participant_b),
                and_(Match.participant_1_id == participant_b, Match.participant_2_id == participant_a),
            )
        )
    ).all()
    wins_a = sum(match.winner_participant_id == participant_a for match in values)
    wins_b = sum(match.winner_participant_id == participant_b for match in values)
    return {"data": {"participant_a": participant_a, "participant_b": participant_b, "meetings": len(values), "wins": {participant_a: wins_a, participant_b: wins_b}, "snapshot_status": "NOT_PUBLISHED"}, "meta": meta()}


@router.get("/matches/{match_id}/insights")
def get_match_insights(match_id: str, session: DbSession) -> dict[str, Any]:
    value = require_match(session, match_id)
    return {"data": {"match": serialize_match(value), "live_state": session.scalars(select(GameStateObservation).where(GameStateObservation.match_id == match_id).order_by(desc(GameStateObservation.observed_at))).first() and "available", "features": {"status": "NOT_YET_COMPUTED"}}, "meta": meta()}


@router.get("/statistics/coverage")
def get_statistics_coverage(session: DbSession) -> dict[str, Any]:
    return {"data": interval_coverage_summary(session), "meta": meta("BWF_LIVE_DERIVED")}


@router.get("/participants/{participant_id}/interval-statistics")
def get_interval_statistics(participant_id: str, session: DbSession) -> dict[str, Any]:
    if not session.get(Participant, participant_id):
        raise HTTPException(status_code=404, detail="Participant not found")
    return {"data": interval_metrics_for_participant(session, participant_id), "meta": meta("BWF_LIVE_DERIVED")}


@router.get("/admin/import-batches")
def list_import_batches(session: DbSession, _: None = Depends(require_admin)) -> dict[str, Any]:
    values = session.scalars(select(ImportBatch).order_by(desc(ImportBatch.started_at))).all()
    return {"data": [{"id": value.id, "status": value.status, "input_row_count": value.input_row_count, "accepted_count": value.accepted_count, "duplicate_count": value.duplicate_count, "rejected_count": value.rejected_count} for value in values], "meta": meta()}
