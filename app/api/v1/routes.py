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
    RecordLineage,
    RankingEntry,
    RankingSnapshot,
    Tournament,
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
    return {"data": {"id": value.id, "full_name": value.full_name, "country_code": value.country_code, "profile_url": value.profile_url, "identity_status": value.identity_status}, "meta": meta("BWF_LIVE_AND_RESOLVED_IDENTITIES")}


@router.get("/players/{player_id}/matches")
def get_player_matches(player_id: str, session: DbSession) -> dict[str, Any]:
    # Name-only historical aliases are intentionally not represented as confirmed player identity matches.
    return {"data": [], "meta": {**meta(), "notice": "Confirmed player-match linkage is available only after identity resolution."}}


@router.get("/players/{player_id}/statistics")
def get_player_statistics(player_id: str, session: DbSession) -> dict[str, Any]:
    return {"data": {"player_id": player_id, "statistics": [], "coverage": interval_coverage_summary(session)}, "meta": {**meta(), "notice": "Player statistics await resolved participant identity linkage."}}


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
