"""Read-only, typed endpoints for a server-side first-party website adapter."""

from __future__ import annotations

from datetime import date, datetime, timezone
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.db.base import get_db
from app.db.models import (
    Event,
    GameStateObservation,
    Match,
    MatchGame,
    Participant,
    ParticipantMember,
    Player,
    RankingEntry,
    RankingSnapshot,
    OfficialTournamentCalendarEntry,
    OfficialTournamentDocument,
    Tournament,
    TournamentClassification,
)
from app.api.v1.website_contract import (
    ApiMeta,
    CapabilityResponse,
    EventSummary,
    GameSummary,
    LiveStateSummary,
    MemberSummary,
    PageInfo,
    ParticipantSummary,
    TournamentSummary,
    WebsiteEventListResponse,
    WebsiteMatch,
    WebsiteMatchListResponse,
    WebsiteMatchResponse,
    WebsitePlayer,
    WebsitePlayerListResponse,
    WebsiteRankingEntry,
    WebsiteRankingListResponse,
    RankingSnapshotMeta,
    WebsiteTournamentListResponse,
    ModelContractResponse,
    ModelReadinessResponse,
    OfficialBracketResponse,
    SeniorParticipantListResponse,
    WebsiteCalendarListResponse,
    WebsiteDrawDocumentListResponse,
    WebsiteHeadToHeadResponse,
    ForecastFieldAvailability,
    WebsiteMatchForecastResponse,
    WebsiteTournamentSimulationResponse,
)
from app.api.v1.website_contract_service import active_senior_participants, approved_tournament_ids, calendar_entries, draw_documents, head_to_head_snapshot, match_forecast_snapshot, model_contract, official_bracket, tournament_simulation_snapshot
from app.modeling.service import model_readiness

router = APIRouter(prefix="/website", tags=["website-integration"])
DbSession = Session


STATUS_MAP = {
    "SCHEDULED": "scheduled",
    "LIVE": "live",
    "COMPLETED": "completed",
    "HISTORICAL_PARTIAL": "completed",
    "CANCELLED": "cancelled",
    "POSTPONED": "scheduled",
    "RETIRED": "retired",
    "WALKOVER": "walkover",
}
COMPLETED_STATUSES = ("COMPLETED", "HISTORICAL_PARTIAL", "RETIRED", "WALKOVER")


def metadata(source: str = "PLATFORM") -> ApiMeta:
    return ApiMeta(timestamp=datetime.now(timezone.utc), source=source)


def normalize_event(value: Event) -> EventSummary:
    raw = value.event_type.upper().strip()
    base = raw.split("-", 1)[0]
    discipline = base if base in {"MS", "WS", "MD", "WD", "XD"} else "UNKNOWN"
    youth_markers = ("U13", "U15", "U17", "U19", "JUNIOR", "YOUTH")
    reference = f"{raw} {value.category or ''}".upper()
    level = "youth" if any(marker in reference for marker in youth_markers) else "senior"
    return EventSummary(
        id=value.id,
        tournament_id=value.tournament_id,
        raw_type=value.event_type,
        discipline=discipline,
        competition_level=level,
        category=value.category,
    )


def make_tournament(value: Tournament, classifications: dict[str, TournamentClassification]) -> TournamentSummary:
    classification = classifications.get(value.id)
    return TournamentSummary(
        id=value.id,
        name=value.name,
        location_raw=value.location_raw,
        country_code=value.country_code,
        start_date=value.start_date.isoformat() if value.start_date else None,
        end_date=value.end_date.isoformat() if value.end_date else None,
        status=value.status,
        classification=classification.raw_label if classification else None,
        available_disciplines=[],
    )


def fetch_context(session: DbSession, matches: list[Match]) -> tuple[
    dict[str, TournamentSummary], dict[str, EventSummary], dict[str, ParticipantSummary], dict[str, list[GameSummary]], dict[str, LiveStateSummary]
]:
    """Fetch related objects in bounded bulk queries to avoid client-side N+1 calls."""
    tournament_ids = {item.tournament_id for item in matches if item.tournament_id}
    event_ids = {item.event_id for item in matches if item.event_id}
    participant_ids = {
        participant_id
        for item in matches
        for participant_id in (item.participant_1_id, item.participant_2_id)
        if participant_id
    }
    match_ids = [item.id for item in matches]

    tournaments = session.scalars(select(Tournament).where(Tournament.id.in_(tournament_ids))).all() if tournament_ids else []
    classifications = session.scalars(
        select(TournamentClassification).where(TournamentClassification.tournament_id.in_(tournament_ids))
    ).all() if tournament_ids else []
    classifications_by_tournament = {item.tournament_id: item for item in classifications}
    events = session.scalars(select(Event).where(Event.id.in_(event_ids))).all() if event_ids else []
    event_summaries = {item.id: normalize_event(item) for item in events}

    events_by_tournament: dict[str, list[EventSummary]] = {}
    for event in event_summaries.values():
        events_by_tournament.setdefault(event.tournament_id, []).append(event)
    tournament_summaries = {
        item.id: make_tournament(item, classifications_by_tournament).model_copy(
            update={"available_disciplines": sorted({event.discipline for event in events_by_tournament.get(item.id, []) if event.discipline != "UNKNOWN"})}
        )
        for item in tournaments
    }

    participants = session.scalars(select(Participant).where(Participant.id.in_(participant_ids))).all() if participant_ids else []
    member_rows = session.scalars(
        select(ParticipantMember).where(ParticipantMember.participant_id.in_(participant_ids)).order_by(ParticipantMember.member_order)
    ).all() if participant_ids else []
    player_ids = {item.player_id for item in member_rows if item.player_id}
    players = session.scalars(select(Player).where(Player.id.in_(player_ids))).all() if player_ids else []
    players_by_id = {item.id: item for item in players}
    members_by_participant: dict[str, list[MemberSummary]] = {}
    for member in member_rows:
        player = players_by_id.get(member.player_id) if member.player_id else None
        member_id = player.id if player else f"{member.participant_id}:member:{member.member_order}"
        member_name = player.full_name if player else (member.source_alias_text or "Unresolved member")
        members_by_participant.setdefault(member.participant_id, []).append(
            MemberSummary(
                id=member_id,
                name=member_name,
                country_code=player.country_code if player else None,
                identity_status=player.identity_status if player else "UNRESOLVED",
                resolved_player_id=player.id if player else None,
            )
        )
    participant_summaries = {
        item.id: ParticipantSummary(
            id=item.id,
            kind="pair" if item.participant_kind == "PAIR" else "player",
            display_name=item.display_name,
            identity_status=item.identity_resolution_status,
            members=members_by_participant.get(item.id, []),
        )
        for item in participants
    }

    games = session.scalars(select(MatchGame).where(MatchGame.match_id.in_(match_ids)).order_by(MatchGame.match_id, MatchGame.game_number)).all() if match_ids else []
    games_by_match: dict[str, list[GameSummary]] = {}
    for game in games:
        games_by_match.setdefault(game.match_id, []).append(
            GameSummary(
                game_number=game.game_number,
                participant_1_score=game.participant_1_score,
                participant_2_score=game.participant_2_score,
                winner_participant_id=game.winner_participant_id,
                status=game.status,
                parse_confidence=game.parse_confidence,
            )
        )

    state_rows = session.scalars(
        select(GameStateObservation).where(GameStateObservation.match_id.in_(match_ids)).order_by(GameStateObservation.match_id, GameStateObservation.observed_at.desc())
    ).all() if match_ids else []
    latest_states: dict[str, LiveStateSummary] = {}
    for state in state_rows:
        if state.match_id in latest_states:
            continue
        latest_states[state.match_id] = LiveStateSummary(
            game_number=state.game_number,
            participant_1_score=state.participant_1_score,
            participant_2_score=state.participant_2_score,
            observed_at=state.observed_at,
            source_observed_at=state.source_observed_at,
            match_status=state.match_status,
            source_precision="SOURCE_TIME" if state.source_observed_at else "COLLECTION_TIME",
        )
    return tournament_summaries, event_summaries, participant_summaries, games_by_match, latest_states


def make_match(
    value: Match,
    tournaments: dict[str, TournamentSummary],
    events: dict[str, EventSummary],
    participants: dict[str, ParticipantSummary],
    games: dict[str, list[GameSummary]],
    states: dict[str, LiveStateSummary],
) -> WebsiteMatch:
    return WebsiteMatch(
        id=value.id,
        source_match_key=value.source_match_key,
        match_date=value.match_date.isoformat() if value.match_date else None,
        scheduled_time=value.scheduled_time,
        actual_start_time=value.actual_start_time,
        status=value.status,
        normalized_status=STATUS_MAP.get(value.status, "unknown"),
        source_completeness=value.source_completeness,
        historical_seed=value.historical_seed_flag,
        tournament=tournaments.get(value.tournament_id) if value.tournament_id else None,
        event=events.get(value.event_id) if value.event_id else None,
        round=value.round_raw,
        court=value.court_name or value.court_code,
        participant_1=participants.get(value.participant_1_id) if value.participant_1_id else None,
        participant_2=participants.get(value.participant_2_id) if value.participant_2_id else None,
        winner_participant_id=value.winner_participant_id,
        score_raw=value.score_raw,
        score_parse_status=value.score_parse_status,
        score_validation_status=value.score_validation_status,
        games=games.get(value.id, []),
        latest_live_state=states.get(value.id),
        source_url=value.source_url,
    )


def list_website_matches(
    session: DbSession,
    scope: Literal["all", "live", "scheduled", "completed"],
    tournament_id: str | None,
    event_id: str | None,
    from_date: date | None,
    to_date: date | None,
    page: int,
    page_size: int,
    participant_ids: set[str] | None = None,
) -> WebsiteMatchListResponse:
    query = select(Match)
    if scope == "live":
        query = query.where(Match.status == "LIVE")
    elif scope == "scheduled":
        query = query.where(Match.status.in_(("SCHEDULED", "POSTPONED")))
    elif scope == "completed":
        query = query.where(Match.status.in_(COMPLETED_STATUSES))
    if tournament_id:
        query = query.where(Match.tournament_id == tournament_id)
    if event_id:
        query = query.where(Match.event_id == event_id)
    if from_date:
        query = query.where(Match.match_date >= from_date)
    if to_date:
        query = query.where(Match.match_date <= to_date)
    # Filter and paginate in SQL. The previous implementation materialised every
    # historical match before slicing, which could exhaust a small deployment.
    allowed_ids = approved_tournament_ids(session)
    if not allowed_ids:
        return WebsiteMatchListResponse(
            data=[],
            pagination=PageInfo(page=page, page_size=page_size, total=0),
            meta=metadata("BWF_LIVE" if scope == "live" else "PLATFORM"),
        )
    query = query.where(Match.tournament_id.in_(allowed_ids))
    if participant_ids:
        query = query.where(or_(Match.participant_1_id.in_(participant_ids), Match.participant_2_id.in_(participant_ids)))
    total = session.scalar(select(func.count()).select_from(query.subquery())) or 0
    values = session.scalars(
        query.order_by(Match.match_date.desc(), Match.actual_start_time.desc(), Match.id)
        .offset((page - 1) * page_size)
        .limit(page_size)
    ).all()
    context = fetch_context(session, values)
    return WebsiteMatchListResponse(
        data=[make_match(value, *context) for value in values],
        pagination=PageInfo(page=page, page_size=page_size, total=total),
        meta=metadata("BWF_LIVE" if scope == "live" else "PLATFORM"),
    )


@router.get("/matches", response_model=WebsiteMatchListResponse)
def list_matches(
    session: Session = Depends(get_db),
    scope: Literal["all", "live", "scheduled", "completed"] = Query("all"),
    tournament_id: str | None = None,
    event_id: str | None = None,
    from_date: date | None = None,
    to_date: date | None = None,
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=100),
) -> WebsiteMatchListResponse:
    return list_website_matches(session, scope, tournament_id, event_id, from_date, to_date, page, page_size)


@router.get("/players/{player_id}/matches", response_model=WebsiteMatchListResponse)
def list_confirmed_player_matches(
    player_id: str,
    session: Session = Depends(get_db),
    scope: Literal["all", "live", "scheduled", "completed"] = Query("completed"),
    page: int = Query(1, ge=1),
    page_size: int = Query(10, ge=1, le=50),
) -> WebsiteMatchListResponse:
    """Return bounded approved-scope history for one confirmed player through resolved participant membership."""
    player = session.get(Player, player_id)
    if player is None or player.identity_status != "CONFIRMED":
        raise HTTPException(status_code=404, detail="Confirmed player not found")
    participant_ids = set(session.scalars(
        select(ParticipantMember.participant_id).where(ParticipantMember.player_id == player_id)
    ).all())
    return list_website_matches(session, scope, None, None, None, None, page, page_size, participant_ids)


@router.get("/matches/{match_id}", response_model=WebsiteMatchResponse)
def get_match(match_id: str, session: Session = Depends(get_db)) -> WebsiteMatchResponse:
    value = session.get(Match, match_id)
    if not value or not value.tournament_id or value.tournament_id not in approved_tournament_ids(session, {value.tournament_id}):
        raise HTTPException(status_code=404, detail="Match not found")
    context = fetch_context(session, [value])
    source = "BWF_LIVE" if value.status == "LIVE" else "PLATFORM"
    return WebsiteMatchResponse(data=make_match(value, *context), meta=metadata(source))


@router.get("/matches/{match_id}/forecast", response_model=WebsiteMatchForecastResponse)
def get_match_forecast(match_id: str, session: Session = Depends(get_db)) -> WebsiteMatchForecastResponse:
    """Return immutable published forecast fields or explicit field-level withholding reasons."""
    availability, snapshot = match_forecast_snapshot(session, match_id)
    field = lambda name: ForecastFieldAvailability(available=availability.available, reason=f"{name}_{availability.reason}")
    return WebsiteMatchForecastResponse(
        match_id=match_id,
        availability=availability,
        win_probability=field("win_probability"),
        confidence=field("confidence"),
        evidence_contributors=field("contributors"),
        uncertainty=field("uncertainty"),
        snapshot=snapshot,
        meta=metadata(),
    )


@router.get("/tournaments", response_model=WebsiteTournamentListResponse)
def list_tournaments(
    session: Session = Depends(get_db),
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=100),
) -> WebsiteTournamentListResponse:
    candidates = session.scalars(select(Tournament).order_by(Tournament.end_date.desc())).all()
    allowed_ids = approved_tournament_ids(session, {item.id for item in candidates})
    eligible = [item for item in candidates if item.id in allowed_ids]
    total = len(eligible)
    values = eligible[(page - 1) * page_size : page * page_size]
    tournament_ids = [item.id for item in values]
    classifications = session.scalars(select(TournamentClassification).where(TournamentClassification.tournament_id.in_(tournament_ids))).all() if tournament_ids else []
    events = session.scalars(select(Event).where(Event.tournament_id.in_(tournament_ids))).all() if tournament_ids else []
    by_tournament = {item.tournament_id: item for item in classifications}
    disciplines: dict[str, set[str]] = {}
    for event in events:
        normalized = normalize_event(event)
        if normalized.discipline != "UNKNOWN":
            disciplines.setdefault(event.tournament_id, set()).add(normalized.discipline)
    data = [
        make_tournament(value, by_tournament).model_copy(update={"available_disciplines": sorted(disciplines.get(value.id, set()))})
        for value in values
    ]
    return WebsiteTournamentListResponse(data=data, pagination=PageInfo(page=page, page_size=page_size, total=total), meta=metadata())


@router.get("/calendar", response_model=WebsiteCalendarListResponse)
def list_calendar_metadata(
    session: Session = Depends(get_db),
    from_date: date | None = None,
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=100),
) -> WebsiteCalendarListResponse:
    """Read only stored metadata from the authorised corporate calendar; no source request occurs."""
    data, total = calendar_entries(session, page=page, page_size=page_size, from_date=from_date)
    return WebsiteCalendarListResponse(data=data, pagination=PageInfo(page=page, page_size=page_size, total=total), meta=metadata("BWF_CORPORATE_CALENDAR"))


@router.get("/calendar/{calendar_entry_id}/draw-documents", response_model=WebsiteDrawDocumentListResponse)
def list_draw_document_metadata(calendar_entry_id: str, session: Session = Depends(get_db)) -> WebsiteDrawDocumentListResponse:
    """Read only document metadata; this endpoint never returns PDF bytes or triggers collection."""
    return WebsiteDrawDocumentListResponse(data=draw_documents(session, calendar_entry_id), meta=metadata("BWF_CORPORATE_CALENDAR"))


@router.get("/active-participants", response_model=SeniorParticipantListResponse)
def list_active_participants(
    session: Session = Depends(get_db),
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=100),
) -> SeniorParticipantListResponse:
    """Return only confirmed player or pair identities with recent approved senior official activity."""
    data, total = active_senior_participants(session, page=page, page_size=page_size)
    return SeniorParticipantListResponse(data=data, pagination=PageInfo(page=page, page_size=page_size, total=total), meta=metadata("BWF_LIVE_AND_RESOLVED_IDENTITIES"))


@router.get("/head-to-head", response_model=WebsiteHeadToHeadResponse)
def get_head_to_head(
    participant_a_id: str = Query(min_length=1, max_length=36),
    participant_b_id: str = Query(min_length=1, max_length=36),
    session: Session = Depends(get_db),
) -> WebsiteHeadToHeadResponse:
    """Return an evidence-backed H2H summary only; never compute a client-side forecast."""
    availability, snapshot = head_to_head_snapshot(
        session,
        participant_a_id=participant_a_id,
        participant_b_id=participant_b_id,
    )
    return WebsiteHeadToHeadResponse(
        participant_a_id=participant_a_id,
        participant_b_id=participant_b_id,
        availability=availability,
        snapshot=snapshot,
        meta=metadata("PLATFORM_MODEL"),
    )


@router.get("/calendar/{calendar_entry_id}/brackets/{discipline}", response_model=OfficialBracketResponse)
def get_official_bracket(
    calendar_entry_id: str,
    discipline: Literal["MS", "WS", "MD", "WD", "XD"],
    session: Session = Depends(get_db),
) -> OfficialBracketResponse:
    """Return a bracket only after direct-PDF parser validation and canonical reconciliation."""
    availability, document_id, topology_id, data = official_bracket(session, calendar_entry_id=calendar_entry_id, discipline=discipline)
    return OfficialBracketResponse(
        availability=availability,
        discipline=discipline,
        calendar_entry_id=calendar_entry_id,
        document_id=document_id,
        topology_id=topology_id,
        data=data,
        meta=metadata("BWF_CORPORATE_CALENDAR"),
    )


@router.get("/calendar/{calendar_entry_id}/simulation", response_model=WebsiteTournamentSimulationResponse)
def get_tournament_simulation(calendar_entry_id: str, session: Session = Depends(get_db)) -> WebsiteTournamentSimulationResponse:
    """Return only a published simulation linked to a reconciled direct BWF draw topology."""
    availability, snapshot = tournament_simulation_snapshot(session, calendar_entry_id)
    return WebsiteTournamentSimulationResponse(
        calendar_entry_id=calendar_entry_id,
        availability=availability,
        snapshot=snapshot,
        meta=metadata("BWF_CORPORATE_CALENDAR"),
    )


@router.get("/model-contract", response_model=ModelContractResponse)
def get_model_contract(session: Session = Depends(get_db)) -> ModelContractResponse:
    """Expose model readiness without claiming forecasts, head-to-head, or simulations before evidence exists."""
    return ModelContractResponse(data=model_contract(session), meta=metadata())


@router.get("/model-readiness", response_model=ModelReadinessResponse)
def get_model_readiness(session: Session = Depends(get_db)) -> ModelReadinessResponse:
    """Expose corpus readiness without training or publishing any model output."""
    return ModelReadinessResponse(data=model_readiness(session), meta=metadata())


@router.get("/tournaments/{tournament_id}/events", response_model=WebsiteEventListResponse)
def list_tournament_events(tournament_id: str, session: Session = Depends(get_db)) -> WebsiteEventListResponse:
    if not session.get(Tournament, tournament_id) or tournament_id not in approved_tournament_ids(session, {tournament_id}):
        raise HTTPException(status_code=404, detail="Tournament not found")
    values = session.scalars(select(Event).where(Event.tournament_id == tournament_id).order_by(Event.event_type)).all()
    return WebsiteEventListResponse(data=[normalize_event(value) for value in values], meta=metadata())


@router.get("/players", response_model=WebsitePlayerListResponse)
def list_players(
    session: Session = Depends(get_db),
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=100),
    search: str | None = Query(None, min_length=2, max_length=100),
) -> WebsitePlayerListResponse:
    query = select(Player).where(Player.identity_status == "CONFIRMED")
    normalized_search = " ".join(search.split()).lower() if search else ""
    if normalized_search:
        query = query.where(func.lower(Player.full_name).contains(normalized_search, autoescape=True))
    total = session.scalar(select(func.count()).select_from(query.subquery())) or 0
    values = session.scalars(
        query.order_by(Player.full_name, Player.id)
        .offset((page - 1) * page_size)
        .limit(page_size)
    ).all()
    data = [WebsitePlayer(id=value.id, full_name=value.full_name, country_code=value.country_code, profile_url=value.profile_url, identity_status=value.identity_status) for value in values]
    return WebsitePlayerListResponse(data=data, pagination=PageInfo(page=page, page_size=page_size, total=total), meta=metadata("BWF_OFFICIAL_PLAYER_PROFILES"))


@router.get("/rankings", response_model=WebsiteRankingListResponse)
def list_rankings(
    session: Session = Depends(get_db),
    ranking_system: Literal["WORLD", "WORLD_TOUR"] = Query("WORLD"),
    discipline: Literal["MS", "WS", "MD", "WD", "XD"] = Query("MS"),
    effective_date: str | None = None,
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=100),
) -> WebsiteRankingListResponse:
    query = select(RankingSnapshot).where(
        RankingSnapshot.ranking_system == ranking_system,
        RankingSnapshot.discipline == discipline,
        RankingSnapshot.population == "SENIOR",
        RankingSnapshot.snapshot_status == "COMPLETE",
    )
    if effective_date:
        query = query.where(RankingSnapshot.effective_date == effective_date)
    snapshot = session.scalar(query.order_by(RankingSnapshot.effective_date.desc(), RankingSnapshot.retrieved_at.desc()))
    if not snapshot:
        return WebsiteRankingListResponse(
            data=[],
            pagination=PageInfo(page=page, page_size=page_size, total=0),
            issues=["ranking_snapshot_unavailable"],
            meta=metadata("BWF_OFFICIAL_RANKINGS"),
        )
    entry_query = select(RankingEntry).where(RankingEntry.snapshot_id == snapshot.id)
    total = session.scalar(select(func.count()).select_from(entry_query.subquery())) or 0
    rows = session.scalars(
        entry_query.order_by(RankingEntry.ranking_position, RankingEntry.subject_display_name)
        .offset((page - 1) * page_size)
        .limit(page_size)
    ).all()
    return WebsiteRankingListResponse(
        data=[
            WebsiteRankingEntry(
                ranking_position=item.ranking_position,
                points=item.points,
                tournament_count=item.tournament_count,
                rank_change=item.rank_change,
                subject_kind=item.subject_kind,
                subject_display_name=item.subject_display_name,
                official_subject_id=item.official_subject_id,
                country_code=item.country_code,
                platform_player_id=item.platform_player_id,
                identity_status=item.identity_status,
            )
            for item in rows
        ],
        pagination=PageInfo(page=page, page_size=page_size, total=total),
        snapshot=RankingSnapshotMeta(
            ranking_system=snapshot.ranking_system,
            population=snapshot.population,
            discipline=snapshot.discipline,
            effective_date=snapshot.effective_date.isoformat(),
            published_week=snapshot.published_week,
            retrieved_at=snapshot.retrieved_at,
            source_url=snapshot.source_url,
            content_hash=snapshot.content_hash,
            snapshot_status=snapshot.snapshot_status,
            issue_summary=snapshot.issue_summary,
        ),
        meta=metadata("BWF_OFFICIAL_RANKINGS"),
    )


@router.get("/capabilities", response_model=CapabilityResponse)
def capabilities(session: Session = Depends(get_db)) -> CapabilityResponse:
    rankings_available = bool(session.scalar(
        select(func.count()).select_from(RankingSnapshot).where(
            RankingSnapshot.population == "SENIOR",
            RankingSnapshot.snapshot_status == "COMPLETE",
        )
    ))
    eligible_calendar_count = session.scalar(
        select(func.count()).select_from(OfficialTournamentCalendarEntry).where(
            OfficialTournamentCalendarEntry.eligibility_status == "ELIGIBLE"
        )
    ) or 0
    eligible_document_count = session.scalar(
        select(func.count())
        .select_from(OfficialTournamentDocument)
        .join(
            OfficialTournamentCalendarEntry,
            OfficialTournamentCalendarEntry.id == OfficialTournamentDocument.calendar_entry_id,
        )
        .where(OfficialTournamentCalendarEntry.eligibility_status == "ELIGIBLE")
    ) or 0
    _, active_participant_count = active_senior_participants(session, page=1, page_size=1)
    contracts = model_contract(session)
    return CapabilityResponse(
        data={
            "calendar": ({"available": True, "source": "BWF_CORPORATE_CALENDAR", "eligible_record_count": eligible_calendar_count, "read_only": True} if eligible_calendar_count else {"available": False, "reason": "no_eligible_calendar_entries_persisted", "eligible_record_count": 0, "read_only": True}),
            "draw_documents": ({"available": True, "source": "BWF_CORPORATE_CALENDAR", "eligible_record_count": eligible_document_count, "read_only": True} if eligible_document_count else {"available": False, "reason": "no_eligible_direct_draw_documents_persisted", "eligible_record_count": 0, "read_only": True}),
            "active_participants": ({"available": True, "source": "BWF_LIVE_AND_RESOLVED_IDENTITIES", "eligible_record_count": active_participant_count} if active_participant_count else {"available": False, "reason": "no_confirmed_active_senior_participants", "eligible_record_count": 0}),
            "rankings": ({"available": True, "source": "BWF_OFFICIAL_RANKINGS"} if rankings_available else {"available": False, "reason": "no_complete_senior_ranking_snapshot"}),
            "draws": {"available": False, "reason": "official_draw_topology_not_yet_validated_and_reconciled"},
            "point_events": {"available": False, "reason": "not_exposed_by_provider"},
            "predictions": contracts["predictions"].model_dump(),
            "head_to_head": contracts["head_to_head"].model_dump(),
            "tournament_simulations": contracts["simulations"].model_dump(),
            "live_states": {"available": True, "caveat": "partial scores and collection timestamps are possible"},
        },
        meta=metadata(),
    )
