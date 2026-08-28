"""Read-only website services for evidence-bounded calendar, participant, bracket, and model contracts."""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api.v1.website_contract import (
    CalendarProvenance,
    ContractAvailability,
    WebsiteMatchForecastSnapshot,
    WebsiteTournamentSimulationSnapshot,
    OfficialBracketNode,
    SeniorParticipantContract,
    WebsiteHeadToHeadSnapshot,
    WebsiteCalendarEntry,
    WebsiteDrawDocument,
)
from app.db.models import (
    Event,
    HeadToHeadSnapshot,
    Match,
    MatchForecastSnapshot,
    MatchParticipantContext,
    ModelSnapshot,
    OfficialDrawNode,
    OfficialDrawNodeReconciliation,
    OfficialDrawTopology,
    OfficialTournamentCalendarEntry,
    OfficialTournamentCalendarSnapshot,
    OfficialTournamentDocument,
    Participant,
    ParticipantMember,
    Player,
    Tournament,
    TournamentClassification,
    TournamentSimulationSnapshot,
)
from app.ingestion.approved_scope import classify_approved_senior_scope

RECENT_ACTIVITY_WINDOW = timedelta(weeks=52)
COMPLETED_ACTIVITY_STATUSES = {"COMPLETED", "RETIRED"}
PUBLISHABLE_TOPOLOGY_STATUS = "VALIDATED_RECONCILED"


def approved_tournament_ids(session: Session, tournament_ids: set[str] | None = None) -> set[str]:
    """Return only canonical tournaments that still meet the approved senior source scope."""
    query = select(Tournament, TournamentClassification).outerjoin(
        TournamentClassification, TournamentClassification.tournament_id == Tournament.id
    )
    if tournament_ids is not None:
        if not tournament_ids:
            return set()
        query = query.where(Tournament.id.in_(tournament_ids))
    approved: set[str] = set()
    for tournament, classification in session.execute(query).all():
        status, _ = classify_approved_senior_scope({
            "name": tournament.source_name_raw or tournament.name,
            "category": tournament.source_category_raw or (classification.raw_label if classification else ""),
        })
        if status == "ELIGIBLE":
            approved.add(tournament.id)
    return approved


def calendar_entries(session: Session, *, page: int, page_size: int, from_date: date | None = None) -> tuple[list[WebsiteCalendarEntry], int]:
    query = (
        select(OfficialTournamentCalendarEntry, OfficialTournamentCalendarSnapshot)
        .join(OfficialTournamentCalendarSnapshot, OfficialTournamentCalendarSnapshot.id == OfficialTournamentCalendarEntry.snapshot_id)
        .where(OfficialTournamentCalendarEntry.eligibility_status == "ELIGIBLE")
        .order_by(OfficialTournamentCalendarEntry.start_date, OfficialTournamentCalendarEntry.name)
    )
    if from_date:
        query = query.where(OfficialTournamentCalendarEntry.end_date >= from_date)
    rows = session.execute(query).all()
    latest_by_source_tournament: dict[str, tuple[OfficialTournamentCalendarEntry, OfficialTournamentCalendarSnapshot]] = {}
    for entry, snapshot in rows:
        existing = latest_by_source_tournament.get(entry.source_tournament_id)
        if existing is None or snapshot.retrieved_at > existing[1].retrieved_at:
            latest_by_source_tournament[entry.source_tournament_id] = (entry, snapshot)
    values = sorted(latest_by_source_tournament.values(), key=lambda item: (item[0].start_date, item[0].name))
    total = len(values)
    paged = values[(page - 1) * page_size : page * page_size]
    return [
        WebsiteCalendarEntry(
            id=entry.id,
            source_tournament_id=entry.source_tournament_id,
            name=entry.name,
            country_code=entry.country_code,
            city=entry.city,
            start_date=entry.start_date.isoformat(),
            end_date=entry.end_date.isoformat(),
            category=entry.category,
            event_url=entry.source_url,
            draw_date_text=entry.draw_date_text,
            eligibility_status="ELIGIBLE",
            eligibility_rationale=entry.eligibility_rationale,
            provenance=CalendarProvenance(
                source_code="BWF_CORPORATE_CALENDAR",
                snapshot_id=snapshot.id,
                source_url=snapshot.source_url,
                retrieved_at=snapshot.retrieved_at,
                content_hash=snapshot.content_hash,
                parser_version=snapshot.parser_version,
                snapshot_status=snapshot.snapshot_status,
            ),
        )
        for entry, snapshot in paged
    ], total


def draw_documents(session: Session, calendar_entry_id: str) -> list[WebsiteDrawDocument]:
    entry = session.get(OfficialTournamentCalendarEntry, calendar_entry_id)
    if entry is None or entry.eligibility_status != "ELIGIBLE":
        return []
    rows = session.scalars(
        select(OfficialTournamentDocument)
        .where(OfficialTournamentDocument.calendar_entry_id == calendar_entry_id)
        .order_by(OfficialTournamentDocument.retrieved_at.desc())
    ).all()
    return [
        WebsiteDrawDocument(
            id=document.id,
            calendar_entry_id=document.calendar_entry_id,
            source_url=document.source_url,
            document_label=document.document_label,
            retrieved_at=document.retrieved_at,
            content_hash=document.content_hash,
            content_type=document.content_type,
            byte_size=document.byte_size,
            parser_version=document.parser_version,
            parser_status=document.parser_status,
            parser_issue=document.parser_issue,
        )
        for document in rows
    ]


def _approved_recent_contexts(session: Session, participant_ids: set[str], *, as_of: date) -> dict[str, list[tuple[Match, Tournament, Event]]]:
    if not participant_ids:
        return {}
    cutoff = as_of - RECENT_ACTIVITY_WINDOW
    rows = session.execute(
        select(MatchParticipantContext.participant_id, Match, Tournament, Event)
        .join(Match, Match.id == MatchParticipantContext.match_id)
        .join(Tournament, Tournament.id == Match.tournament_id)
        .join(Event, Event.id == Match.event_id)
        .where(
            MatchParticipantContext.participant_id.in_(participant_ids),
            Match.status.in_(COMPLETED_ACTIVITY_STATUSES),
            Match.match_date >= cutoff,
        )
    ).all()
    by_participant: dict[str, list[tuple[Match, Tournament, Event]]] = {}
    for participant_id, match, tournament, event in rows:
        status, _ = classify_approved_senior_scope(
            {"name": tournament.source_name_raw or tournament.name, "category": tournament.source_category_raw or ""},
            {"live_detail": {"event": event.event_type, "category": event.category}, "match_detail": {"event": event.event_type, "category": event.category}},
        )
        if status == "ELIGIBLE":
            by_participant.setdefault(participant_id, []).append((match, tournament, event))
    return by_participant


def active_senior_participants(session: Session, *, page: int, page_size: int, as_of: date | None = None) -> tuple[list[SeniorParticipantContract], int]:
    as_of = as_of or datetime.now(timezone.utc).date()
    cutoff = as_of - RECENT_ACTIVITY_WINDOW
    candidate_ids = set(session.scalars(
        select(MatchParticipantContext.participant_id)
        .join(Match, Match.id == MatchParticipantContext.match_id)
        .where(
            Match.status.in_(COMPLETED_ACTIVITY_STATUSES),
            Match.match_date >= cutoff,
        )
        .distinct()
    ).all())
    if not candidate_ids:
        return [], 0
    # Legacy participant wrappers may remain unresolved even when every required
    # underlying player identity has been provider-confirmed. Public eligibility is
    # therefore based on complete confirmed membership plus approved recent context,
    # never on a name match or a partially resolved wrapper.
    participants = session.scalars(select(Participant).where(Participant.id.in_(candidate_ids)).order_by(Participant.display_name)).all()
    member_rows = session.scalars(select(ParticipantMember).where(ParticipantMember.participant_id.in_([item.id for item in participants]))).all() if participants else []
    member_ids: dict[str, list[str]] = {}
    for member in member_rows:
        if member.player_id:
            member_ids.setdefault(member.participant_id, []).append(member.player_id)
    player_rows = session.scalars(select(Player).where(Player.id.in_({player_id for values in member_ids.values() for player_id in values}))).all() if member_ids else []
    players = {player.id: player for player in player_rows}
    contexts = _approved_recent_contexts(session, candidate_ids, as_of=as_of)
    active: list[SeniorParticipantContract] = []
    for participant in participants:
        resolved_members = member_ids.get(participant.id, [])
        expected_members = 2 if participant.participant_kind == "PAIR" else 1
        if len(resolved_members) != expected_members or any(players.get(member_id) is None or players[member_id].identity_status != "CONFIRMED" for member_id in resolved_members):
            continue
        matches = contexts.get(participant.id, [])
        if not matches:
            continue
        latest = max(match.match_date for match, _, _ in matches if match.match_date is not None)
        active.append(SeniorParticipantContract(
            id=participant.id,
            kind="pair" if participant.participant_kind == "PAIR" else "player",
            display_name=participant.display_name,
            member_ids=resolved_members,
            identity_status="CONFIRMED",
            activity_status="ACTIVE_RECENT_OFFICIAL_PARTICIPATION",
            recent_eligible_match_count=len({match.id for match, _, _ in matches}),
            latest_eligible_match_date=latest.isoformat(),
            eligibility_rationale="Every required underlying member is provider-confirmed and has a dated COMPLETED or RETIRED match within 52 weeks in an approved senior competition category.",
        ))
    return active[(page - 1) * page_size : page * page_size], len(active)


def _active_senior_participant_contract(
    session: Session, participant_id: str, *, as_of: date
) -> SeniorParticipantContract | None:
    """Apply the same current-senior gate to one requested Head-to-Head subject.

    This deliberately repeats the membership and approved-context checks rather than
    accepting a name or an old HeadToHeadSnapshot as proof of present eligibility.
    """

    participant = session.get(Participant, participant_id)
    if participant is None:
        return None
    members = session.scalars(
        select(ParticipantMember).where(ParticipantMember.participant_id == participant.id)
    ).all()
    expected_members = 2 if participant.participant_kind == "PAIR" else 1
    if len(members) != expected_members or any(member.player_id is None for member in members):
        return None
    player_ids = [member.player_id for member in members if member.player_id]
    players = {
        player.id: player
        for player in session.scalars(select(Player).where(Player.id.in_(player_ids))).all()
    }
    if len(players) != expected_members or any(
        players[player_id].identity_status != "CONFIRMED" for player_id in player_ids
    ):
        return None
    contexts = _approved_recent_contexts(session, {participant.id}, as_of=as_of).get(participant.id, [])
    if not contexts:
        return None
    latest = max(match.match_date for match, _, _ in contexts if match.match_date is not None)
    return SeniorParticipantContract(
        id=participant.id,
        kind="pair" if participant.participant_kind == "PAIR" else "player",
        display_name=participant.display_name,
        member_ids=player_ids,
        identity_status="CONFIRMED",
        activity_status="ACTIVE_RECENT_OFFICIAL_PARTICIPATION",
        recent_eligible_match_count=len({match.id for match, _, _ in contexts}),
        latest_eligible_match_date=latest.isoformat(),
        eligibility_rationale="Every required underlying member is provider-confirmed and has a dated COMPLETED or RETIRED match within 52 weeks in an approved senior competition category.",
    )


def head_to_head_snapshot(
    session: Session, *, participant_a_id: str, participant_b_id: str, as_of: date | None = None
) -> tuple[ContractAvailability, WebsiteHeadToHeadSnapshot | None]:
    """Return only a persisted, current-senior, validation-backed H2H summary.

    No probability, scoreline, or forecast is calculated in this read path. Both
    requested subjects must independently pass the active-senior contract today.
    """

    prerequisites = [
        "two distinct confirmed active senior participants or verified current pairs",
        "dated completed or retired matches within the prior 52 weeks in approved senior scope",
        "stored validated head-to-head summary with source evidence",
    ]
    if participant_a_id == participant_b_id:
        return ContractAvailability(available=False, reason="distinct_participants_required", prerequisites=prerequisites, eligible_record_count=0), None
    today = as_of or datetime.now(timezone.utc).date()
    if not _active_senior_participant_contract(session, participant_a_id, as_of=today) or not _active_senior_participant_contract(session, participant_b_id, as_of=today):
        return ContractAvailability(available=False, reason="active_senior_participant_required", prerequisites=prerequisites, eligible_record_count=0), None
    stored_a, stored_b = sorted((participant_a_id, participant_b_id))
    snapshot = session.scalar(
        select(HeadToHeadSnapshot)
        .where(
            HeadToHeadSnapshot.participant_a_id == stored_a,
            HeadToHeadSnapshot.participant_b_id == stored_b,
            HeadToHeadSnapshot.summary_status == "VALIDATED",
        )
        .order_by(HeadToHeadSnapshot.input_cutoff.desc(), HeadToHeadSnapshot.created_at.desc())
    )
    if snapshot is None:
        return ContractAvailability(available=False, reason="no_validated_head_to_head_snapshot", prerequisites=prerequisites, eligible_record_count=0), None
    if snapshot.eligible_meetings < 1 or snapshot.participant_a_wins + snapshot.participant_b_wins != snapshot.eligible_meetings:
        return ContractAvailability(available=False, reason="head_to_head_snapshot_invariant_failed", prerequisites=prerequisites, eligible_record_count=0), None
    if participant_a_id == stored_a:
        a_wins, b_wins = snapshot.participant_a_wins, snapshot.participant_b_wins
    else:
        a_wins, b_wins = snapshot.participant_b_wins, snapshot.participant_a_wins
    return ContractAvailability(available=True, reason="validated_active_senior_head_to_head_snapshot", prerequisites=prerequisites, eligible_record_count=snapshot.eligible_meetings), WebsiteHeadToHeadSnapshot(
        participant_a_id=participant_a_id,
        participant_b_id=participant_b_id,
        input_cutoff=snapshot.input_cutoff,
        eligible_meetings=snapshot.eligible_meetings,
        participant_a_wins=a_wins,
        participant_b_wins=b_wins,
        evidence=snapshot.evidence,
    )


def model_contract(session: Session) -> dict[str, ContractAvailability]:
    active_models = session.scalars(select(ModelSnapshot).where(ModelSnapshot.model_status == "ACTIVE", ModelSnapshot.calibration_status == "EVALUATED")).all()
    models_ready = [item for item in active_models if item.training_cutoff and item.evaluation_summary is not None and item.activated_at]
    h2h_count = session.scalar(select(func.count()).select_from(HeadToHeadSnapshot).where(HeadToHeadSnapshot.summary_status == "VALIDATED")) or 0
    forecast_count = session.scalar(select(func.count()).select_from(MatchForecastSnapshot).where(MatchForecastSnapshot.forecast_status == "PUBLISHED")) or 0
    prerequisites = ["approved senior-only source scope", "confirmed participant identity", "timestamped input cutoff", "versioned methodology", "validated source provenance"]
    return {
        "model": ContractAvailability(available=bool(models_ready), reason="active_validated_model_available" if models_ready else "no_active_evaluated_model_snapshot", prerequisites=prerequisites + ["calibration and accuracy evaluation"], eligible_record_count=len(models_ready)),
        "predictions": ContractAvailability(available=bool(models_ready and forecast_count), reason="published_pre_match_forecasts_available" if models_ready and forecast_count else "no_published_pre_match_forecast_snapshot", prerequisites=prerequisites + ["active evaluated model", "pre-match generated forecast", "probabilities summing to 10,000 basis points"], eligible_record_count=forecast_count),
        "head_to_head": ContractAvailability(available=bool(h2h_count), reason="validated_head_to_head_available" if h2h_count else "no_validated_head_to_head_snapshot", prerequisites=prerequisites + ["pair of confirmed active participants", "eligible completed match history"], eligible_record_count=h2h_count),
        "simulations": ContractAvailability(available=False, reason="bracket_transition_topology_and_monte_carlo_contract_not_yet_implemented", prerequisites=prerequisites + ["published directed official draw topology", "validated reconciliation to canonical matches", "active evaluated model", "versioned Monte Carlo advancement run"], eligible_record_count=0),
    }


def match_forecast_snapshot(session: Session, match_id: str) -> tuple[ContractAvailability, WebsiteMatchForecastSnapshot | None]:
    """Expose a published pre-match forecast only when it is both senior-safe and model-validated."""
    match = session.get(Match, match_id)
    prerequisites = [
        "approved senior-only source scope",
        "confirmed participant identity",
        "timestamped input cutoff",
        "active evaluated model",
        "published pre-match forecast",
        "probabilities summing to 10,000 basis points",
    ]
    if match is None or not match.tournament_id or match.tournament_id not in approved_tournament_ids(session, {match.tournament_id}):
        return ContractAvailability(available=False, reason="eligible_match_not_found", prerequisites=prerequisites, eligible_record_count=0), None
    if match.status in {"COMPLETED", "HISTORICAL_PARTIAL", "RETIRED", "WALKOVER"} or match.winner_participant_id is not None:
        return ContractAvailability(available=False, reason="official_result_available_prediction_is_historical_audit_only", prerequisites=prerequisites, eligible_record_count=0), None
    row = session.execute(
        select(MatchForecastSnapshot, ModelSnapshot)
        .join(ModelSnapshot, ModelSnapshot.id == MatchForecastSnapshot.model_snapshot_id)
        .where(
            MatchForecastSnapshot.match_id == match_id,
            MatchForecastSnapshot.forecast_status == "PUBLISHED",
            ModelSnapshot.model_status == "ACTIVE",
            ModelSnapshot.calibration_status == "EVALUATED",
        )
        .order_by(MatchForecastSnapshot.input_cutoff.desc(), MatchForecastSnapshot.generated_at.desc())
    ).first()
    if row is None:
        return ContractAvailability(available=False, reason="no_published_pre_match_forecast_snapshot", prerequisites=prerequisites, eligible_record_count=0), None
    forecast, model = row
    if forecast.participant_1_win_probability_bps + forecast.participant_2_win_probability_bps != 10_000:
        return ContractAvailability(available=False, reason="forecast_probability_total_invalid", prerequisites=prerequisites, eligible_record_count=0), None
    return ContractAvailability(available=True, reason="published_pre_match_forecast_snapshot", prerequisites=prerequisites, eligible_record_count=1), WebsiteMatchForecastSnapshot(
        match_id=match_id,
        model_key=model.model_key,
        model_version=model.model_version,
        input_cutoff=forecast.input_cutoff,
        generated_at=forecast.generated_at,
        participant_1_win_probability_bps=forecast.participant_1_win_probability_bps,
        participant_2_win_probability_bps=forecast.participant_2_win_probability_bps,
        confidence_label=forecast.confidence_label,
        uncertainty_summary=forecast.uncertainty_summary,
        evidence_contributors=[str(value) for value in forecast.evidence_contributors],
        provenance=forecast.provenance,
    )


def tournament_simulation_snapshot(session: Session, calendar_entry_id: str) -> tuple[ContractAvailability, WebsiteTournamentSimulationSnapshot | None]:
    """Expose a simulation only if it is tied to an eligible calendar entry and a reconciled direct-draw topology."""
    prerequisites = [
        "eligible official calendar entry",
        "canonical tournament link",
        "published official draw topology",
        "validated reconciliation to canonical matches",
        "active evaluated model",
        "published tournament simulation snapshot",
    ]
    entry = session.get(OfficialTournamentCalendarEntry, calendar_entry_id)
    if entry is None or entry.eligibility_status != "ELIGIBLE":
        return ContractAvailability(available=False, reason="eligible_calendar_entry_not_found", prerequisites=prerequisites, eligible_record_count=0), None
    return ContractAvailability(
        available=False,
        reason="bracket_transition_topology_and_monte_carlo_contract_not_yet_implemented",
        prerequisites=prerequisites + ["verified directed topology transitions", "versioned Monte Carlo advancement outputs"],
        eligible_record_count=0,
    ), None
    tournaments = session.scalars(select(Tournament).where(Tournament.source_url == entry.source_url)).all() if entry.source_url else []
    eligible_tournaments = [item for item in tournaments if item.id in approved_tournament_ids(session, {item.id for item in tournaments})]
    if len(eligible_tournaments) != 1:
        return ContractAvailability(available=False, reason="canonical_tournament_link_not_available", prerequisites=prerequisites, eligible_record_count=0), None
    document_ids = set(session.scalars(select(OfficialTournamentDocument.id).where(OfficialTournamentDocument.calendar_entry_id == calendar_entry_id)).all())
    if not document_ids:
        return ContractAvailability(available=False, reason="no_authorised_direct_draw_document", prerequisites=prerequisites, eligible_record_count=0), None
    row = session.execute(
        select(TournamentSimulationSnapshot, ModelSnapshot, OfficialDrawTopology)
        .join(ModelSnapshot, ModelSnapshot.id == TournamentSimulationSnapshot.model_snapshot_id)
        .join(OfficialDrawTopology, OfficialDrawTopology.id == TournamentSimulationSnapshot.draw_topology_id)
        .where(
            TournamentSimulationSnapshot.tournament_id == eligible_tournaments[0].id,
            TournamentSimulationSnapshot.simulation_status == "PUBLISHED",
            ModelSnapshot.model_status == "ACTIVE",
            ModelSnapshot.calibration_status == "EVALUATED",
            OfficialDrawTopology.topology_status == PUBLISHABLE_TOPOLOGY_STATUS,
        )
        .order_by(TournamentSimulationSnapshot.input_cutoff.desc())
    ).first()
    if row is None:
        return ContractAvailability(available=False, reason="no_published_tournament_simulation_snapshot", prerequisites=prerequisites, eligible_record_count=0), None
    simulation, model, topology = row
    if topology.document_id not in document_ids:
        return ContractAvailability(available=False, reason="simulation_topology_not_linked_to_calendar_document", prerequisites=prerequisites, eligible_record_count=0), None
    return ContractAvailability(available=True, reason="published_reconciled_tournament_simulation_snapshot", prerequisites=prerequisites, eligible_record_count=1), WebsiteTournamentSimulationSnapshot(
        calendar_entry_id=calendar_entry_id,
        tournament_id=simulation.tournament_id,
        model_key=model.model_key,
        model_version=model.model_version,
        draw_topology_id=simulation.draw_topology_id,
        input_cutoff=simulation.input_cutoff,
        simulation_count=simulation.simulation_count,
        probability_payload=simulation.probability_payload,
        provenance=simulation.provenance,
    )


def official_bracket(session: Session, *, calendar_entry_id: str, discipline: str) -> tuple[ContractAvailability, str | None, str | None, list[OfficialBracketNode]]:
    entry = session.get(OfficialTournamentCalendarEntry, calendar_entry_id)
    if entry is None or entry.eligibility_status != "ELIGIBLE":
        return ContractAvailability(available=False, reason="eligible_calendar_entry_not_found", prerequisites=["eligible official calendar entry"], eligible_record_count=0), None, None, []
    document_ids = session.scalars(select(OfficialTournamentDocument.id).where(OfficialTournamentDocument.calendar_entry_id == calendar_entry_id)).all()
    if not document_ids:
        return ContractAvailability(available=False, reason="no_authorised_direct_draw_document", prerequisites=["direct BWF draw PDF emitted by the corporate calendar", "captured immutable document metadata"], eligible_record_count=0), None, None, []
    topology = session.scalar(select(OfficialDrawTopology).where(OfficialDrawTopology.document_id.in_(document_ids), OfficialDrawTopology.discipline == discipline).order_by(OfficialDrawTopology.updated_at.desc()))
    base_requirements = ["direct BWF draw PDF emitted by the corporate calendar", "parser-validated topology", "reconciliation to canonical matches"]
    if topology is None:
        return ContractAvailability(available=False, reason="official_document_captured_parser_not_validated", prerequisites=base_requirements, eligible_record_count=0), None, None, []
    if topology.topology_status != PUBLISHABLE_TOPOLOGY_STATUS:
        return ContractAvailability(available=False, reason=f"topology_{topology.topology_status.lower()}", prerequisites=base_requirements, eligible_record_count=0), topology.document_id, topology.id, []
    nodes = session.scalars(select(OfficialDrawNode).where(OfficialDrawNode.topology_id == topology.id).order_by(OfficialDrawNode.display_order)).all()
    reconciliations = session.scalars(select(OfficialDrawNodeReconciliation).where(OfficialDrawNodeReconciliation.node_id.in_([item.id for item in nodes]))).all() if nodes else []
    reconciliation_by_node = {item.node_id: item for item in reconciliations}
    if len(reconciliation_by_node) != len(nodes) or any(item.reconciliation_status != "CANONICAL" for item in reconciliations):
        return ContractAvailability(available=False, reason="topology_nodes_not_fully_reconciled", prerequisites=base_requirements, eligible_record_count=0), topology.document_id, topology.id, []
    return ContractAvailability(available=True, reason="official_draw_validated_and_reconciled", prerequisites=base_requirements, eligible_record_count=len(nodes)), topology.document_id, topology.id, [OfficialBracketNode(source_node_key=node.source_node_key, round_label=node.round_label, display_order=node.display_order, participant_1_label=node.participant_1_label, participant_2_label=node.participant_2_label, winner_label=node.winner_label, score_text=node.score_text, reconciliation_status=reconciliation_by_node[node.id].reconciliation_status, canonical_match_id=reconciliation_by_node[node.id].match_id) for node in nodes]
