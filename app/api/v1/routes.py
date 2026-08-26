from __future__ import annotations

from datetime import datetime, timezone
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import and_, desc, or_, select
from sqlalchemy.orm import Session

from app.api.dependencies import require_admin
from app.db.base import get_db
from app.db.models import (
    Event,
    GameIntervalAssessment,
    GameStateObservation,
    ImportBatch,
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
from app.ingestion.player_profiles.service import (
    NO_EXACT_CANDIDATE_CASE_TYPE,
    NO_RECENT_SENIOR_ACTIVITY_CASE_TYPE,
    NO_SENIOR_CONTEXT_CASE_TYPE,
    RECENT_SENIOR_ELIGIBLE_CASE_TYPE,
    RESOLVER_VERSION,
    context_summary_for_player,
    run_full_queue,
    run_local_classification_sweep,
)
from app.statistics.service import interval_coverage_summary, interval_metrics_for_participant

router = APIRouter(tags=["v1"])
DbSession = Annotated[Session, Depends(get_db)]


def meta(source: str = "PLATFORM") -> dict[str, Any]:
    return {"timestamp": datetime.now(timezone.utc).isoformat(), "source": source, "api_version": "v1"}


def page_payload(items: list[Any], page: int, page_size: int, total: int, source: str = "PLATFORM") -> dict[str, Any]:
    return {"data": items, "pagination": {"page": page, "page_size": page_size, "total": total}, "meta": meta(source)}


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
    # Name-only historical aliases are intentionally not represented as confirmed player identity matches.
    return {"data": [], "meta": {**meta(), "notice": "Confirmed player-match linkage is available only after identity resolution."}}


@router.get("/players/{player_id}/statistics")
def get_player_statistics(player_id: str, session: DbSession) -> dict[str, Any]:
    player = session.get(Player, player_id)
    if not player:
        raise HTTPException(status_code=404, detail="Player not found")
    activity = context_summary_for_player(session, player)
    if not activity.eligible_for_profile_search:
        return {"data": {"player_id": player_id, "statistics": [], "coverage": interval_coverage_summary(session), "activity_status": activity.activity_status, "trusted_statistics_eligible": False, "activity_evidence": activity.evidence()}, "meta": {**meta(), "notice": "Trusted player statistics are withheld until confirmed identity has a dated COMPLETED or RETIRED senior, non-Para official match within the prior 52 weeks."}}
    return {"data": {"player_id": player_id, "statistics": [], "coverage": interval_coverage_summary(session), "activity_status": activity.activity_status, "trusted_statistics_eligible": True, "activity_evidence": activity.evidence()}, "meta": {**meta(), "notice": "Player statistics await resolved participant identity linkage and currently active official participation evidence."}}


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
    query = select(PlayerIdentityLink).where(PlayerIdentityLink.decision_status.in_(("CONFLICTED", "PROVISIONAL_AUTO")))
    total = len(session.scalars(query).all())
    rows = session.scalars(query.order_by(desc(PlayerIdentityLink.decided_at)).offset((page - 1) * page_size).limit(page_size)).all()
    return page_payload([
        {"link_id": row.id, "alias_id": row.alias_id, "player_id": row.player_id, "status": row.decision_status,
         "decision_class": row.decision_class, "score": row.score, "rationale": row.rationale, "evidence": row.evidence}
        for row in rows
    ], page, page_size, total, "BWF_OFFICIAL_PLAYER_PROFILES")


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
    total = len(session.scalars(query).all())
    values = session.scalars(query.order_by(desc(Match.match_date)).offset((page - 1) * page_size).limit(page_size)).all()
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
    return {"data": {"participant_a": participant_a, "participant_b": participant_b, "meetings": len(values), "wins": {participant_a: wins_a, participant_b: wins_b}}, "meta": meta()}


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
