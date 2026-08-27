"""Evidence-gated model, forecast, head-to-head, and tournament simulation producers."""

from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timezone
from math import log
from typing import Any

from sqlalchemy import and_, or_, select
from sqlalchemy.orm import Session

from app.api.v1.website_contract_service import approved_tournament_ids
from app.core.config import Settings, get_settings
from app.db.models import (
    Event,
    HeadToHeadSnapshot,
    Match,
    MatchForecastSnapshot,
    ModelSnapshot,
    OfficialDrawNode,
    OfficialDrawNodeReconciliation,
    OfficialDrawTopology,
    OfficialTournamentCalendarEntry,
    OfficialTournamentDocument,
    Participant,
    ParticipantMember,
    Player,
    Tournament,
    TournamentSimulationSnapshot,
)

MODEL_KEY = "bwf-elo-baseline"
MODEL_VERSION = "1.0.0"
MIN_TRAINING_MATCHES = 10
COMPLETED_STATUSES = ("COMPLETED", "RETIRED")


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _confirmed_participant_ids(session: Session) -> set[str]:
    """Return participants whose complete membership has provider-confirmed identities."""
    participants = session.scalars(select(Participant)).all()
    member_rows = session.execute(
        select(ParticipantMember.participant_id, ParticipantMember.player_id, Player.identity_status)
        .outerjoin(Player, Player.id == ParticipantMember.player_id)
    ).all()
    by_participant: dict[str, list[tuple[str | None, str | None]]] = defaultdict(list)
    for participant_id, player_id, identity_status in member_rows:
        by_participant[participant_id].append((player_id, identity_status))
    confirmed: set[str] = set()
    for participant in participants:
        members = by_participant.get(participant.id, [])
        expected = 2 if participant.participant_kind == "PAIR" else 1
        if participant.identity_resolution_status == "CONFIRMED" and len(members) == expected and all(
            player_id is not None and identity_status == "CONFIRMED" for player_id, identity_status in members
        ):
            confirmed.add(participant.id)
    return confirmed


def _training_matches(session: Session, confirmed_ids: set[str]) -> list[Match]:
    if not confirmed_ids:
        return []
    return session.scalars(
        select(Match)
        .where(
            Match.status.in_(COMPLETED_STATUSES),
            Match.score_validation_status == "VALID",
            Match.winner_participant_id.is_not(None),
            Match.participant_1_id.in_(confirmed_ids),
            Match.participant_2_id.in_(confirmed_ids),
        )
        .order_by(Match.match_date, Match.created_at, Match.id)
    ).all()


def _elo_probability(rating_a: float, rating_b: float) -> float:
    return 1.0 / (1.0 + 10.0 ** ((rating_b - rating_a) / 400.0))


def _evaluate_and_fit(matches: list[Match]) -> tuple[dict[str, float], dict[str, Any]]:
    ratings: dict[str, float] = defaultdict(lambda: 1500.0)
    brier_sum = 0.0
    log_loss_sum = 0.0
    correct = 0
    for match in matches:
        p1, p2 = match.participant_1_id, match.participant_2_id
        if not p1 or not p2 or not match.winner_participant_id:
            continue
        probability = _elo_probability(ratings[p1], ratings[p2])
        actual = 1.0 if match.winner_participant_id == p1 else 0.0
        brier_sum += (probability - actual) ** 2
        log_loss_sum += -(actual * log(max(probability, 1e-9)) + (1 - actual) * log(max(1 - probability, 1e-9)))
        correct += int((probability >= 0.5) == bool(actual))
        expected = probability
        ratings[p1] += 20.0 * (actual - expected)
        ratings[p2] += 20.0 * ((1.0 - actual) - (1.0 - expected))
    count = len(matches)
    evaluation = {
        "evaluation_method": "walk_forward_elo",
        "match_count": count,
        "accuracy": round(correct / count, 6) if count else None,
        "brier_score": round(brier_sum / count, 6) if count else None,
        "log_loss": round(log_loss_sum / count, 6) if count else None,
        "calibration_status": "EVALUATED" if count >= MIN_TRAINING_MATCHES else "INSUFFICIENT_SAMPLE",
    }
    return dict(ratings), evaluation


def _active_model(session: Session) -> ModelSnapshot | None:
    return session.scalar(
        select(ModelSnapshot)
        .where(ModelSnapshot.model_status == "ACTIVE", ModelSnapshot.calibration_status == "EVALUATED")
        .order_by(ModelSnapshot.training_cutoff.desc(), ModelSnapshot.activated_at.desc())
    )


def _upsert_model(session: Session, matches: list[Match], ratings: dict[str, float], evaluation: dict[str, Any]) -> ModelSnapshot | None:
    if len(matches) < MIN_TRAINING_MATCHES:
        return None
    last_date = max(match.match_date for match in matches if match.match_date is not None)
    cutoff = datetime(last_date.year, last_date.month, last_date.day, tzinfo=timezone.utc)
    version = f"{MODEL_VERSION}+{last_date.isoformat()}-{len(matches)}"
    existing = session.scalar(select(ModelSnapshot).where(ModelSnapshot.model_key == MODEL_KEY, ModelSnapshot.model_version == version))
    if existing:
        return existing
    session.query(ModelSnapshot).filter(ModelSnapshot.model_status == "ACTIVE").update({"model_status": "RETIRED"}, synchronize_session=False)
    model = ModelSnapshot(
        model_key=MODEL_KEY,
        model_version=version,
        model_status="ACTIVE",
        training_cutoff=cutoff,
        input_contract={
            "source_scope": "confirmed participant identities and validated completed official matches",
            "features": ["participant_elo_rating"],
            "initial_rating": 1500,
            "k_factor": 20,
        },
        calibration_status="EVALUATED",
        evaluation_summary=evaluation,
        methodology_reference="Internal deterministic walk-forward Elo baseline; replace with a separately evaluated model before production use.",
        activated_at=utcnow(),
    )
    session.add(model)
    session.flush()
    return model


def _publish_forecasts(session: Session, model: ModelSnapshot, ratings: dict[str, float], settings: Settings) -> int:
    confirmed_ids = set(ratings)
    allowed_tournaments = approved_tournament_ids(session)
    matches = session.scalars(
        select(Match)
        .where(
            Match.status == "SCHEDULED",
            Match.match_date >= utcnow().date(),
            Match.tournament_id.in_(allowed_tournaments) if allowed_tournaments else Match.id == "__none__",
            Match.participant_1_id.in_(confirmed_ids),
            Match.participant_2_id.in_(confirmed_ids),
        )
        .order_by(Match.match_date, Match.scheduled_time, Match.id)
        .limit(settings.modeling_max_forecasts_per_run)
    ).all()
    generated = 0
    for match in matches:
        cutoff = utcnow()
        if match.scheduled_time and match.scheduled_time <= cutoff:
            continue
        if session.scalar(select(MatchForecastSnapshot.id).where(
            MatchForecastSnapshot.model_snapshot_id == model.id,
            MatchForecastSnapshot.match_id == match.id,
            MatchForecastSnapshot.input_cutoff == model.training_cutoff,
        )):
            continue
        probability = _elo_probability(ratings[match.participant_1_id], ratings[match.participant_2_id])
        p1_bps = max(1, min(9999, round(probability * 10000)))
        p2_bps = 10000 - p1_bps
        margin = abs(p1_bps - p2_bps)
        confidence = "HIGH" if margin >= 2500 else "MEDIUM" if margin >= 1000 else "LOW"
        session.add(MatchForecastSnapshot(
            model_snapshot_id=model.id,
            match_id=match.id,
            input_cutoff=model.training_cutoff,
            generated_at=cutoff,
            forecast_status="PUBLISHED",
            participant_1_win_probability_bps=p1_bps,
            participant_2_win_probability_bps=p2_bps,
            confidence_label=confidence,
            uncertainty_summary="Deterministic Elo baseline; uncertainty excludes injuries, conditions, and late lineup changes.",
            evidence_contributors=["validated_completed_match_history", "confirmed_participant_identity"],
            provenance={"source": "PLATFORM_MODEL", "model_key": model.model_key, "model_version": model.model_version},
        ))
        generated += 1
    return generated


def _publish_h2h_snapshots(session: Session, confirmed_ids: set[str], matches: list[Match]) -> int:
    grouped: dict[tuple[str, str], list[Match]] = defaultdict(list)
    for match in matches:
        if not match.participant_1_id or not match.participant_2_id:
            continue
        a, b = sorted((match.participant_1_id, match.participant_2_id))
        grouped[(a, b)].append(match)
    created = 0
    for (a, b), meetings in grouped.items():
        if a not in confirmed_ids or b not in confirmed_ids:
            continue
        dated = [item.match_date for item in meetings if item.match_date]
        if not dated:
            continue
        cutoff = datetime(max(dated).year, max(dated).month, max(dated).day, tzinfo=timezone.utc)
        if session.scalar(select(HeadToHeadSnapshot.id).where(
            HeadToHeadSnapshot.participant_a_id == a,
            HeadToHeadSnapshot.participant_b_id == b,
            HeadToHeadSnapshot.input_cutoff == cutoff,
        )):
            continue
        a_wins = sum(item.winner_participant_id == a for item in meetings)
        b_wins = sum(item.winner_participant_id == b for item in meetings)
        session.add(HeadToHeadSnapshot(
            participant_a_id=a,
            participant_b_id=b,
            input_cutoff=cutoff,
            summary_status="VALIDATED",
            eligible_meetings=len(meetings),
            participant_a_wins=a_wins,
            participant_b_wins=b_wins,
            evidence={"match_ids": [item.id for item in meetings], "source_scope": "validated completed official matches"},
        ))
        created += 1
    return created


def _publish_simulations(session: Session, model: ModelSnapshot, ratings: dict[str, float], settings: Settings) -> int:
    rows = session.execute(
        select(OfficialDrawTopology, OfficialTournamentDocument, OfficialTournamentCalendarEntry, Tournament)
        .join(OfficialTournamentDocument, OfficialTournamentDocument.id == OfficialDrawTopology.document_id)
        .join(OfficialTournamentCalendarEntry, OfficialTournamentCalendarEntry.id == OfficialTournamentDocument.calendar_entry_id)
        .join(Tournament, Tournament.source_url == OfficialTournamentCalendarEntry.source_url)
        .where(OfficialDrawTopology.topology_status == "VALIDATED_RECONCILED")
    ).all()
    created = 0
    for topology, document, entry, tournament in rows:
        if tournament.id not in approved_tournament_ids(session, {tournament.id}):
            continue
        if session.scalar(select(TournamentSimulationSnapshot.id).where(
            TournamentSimulationSnapshot.model_snapshot_id == model.id,
            TournamentSimulationSnapshot.tournament_id == tournament.id,
            TournamentSimulationSnapshot.input_cutoff == model.training_cutoff,
        )):
            continue
        nodes = session.scalars(select(OfficialDrawNode).where(OfficialDrawNode.topology_id == topology.id).order_by(OfficialDrawNode.display_order)).all()
        reconciliations = session.scalars(select(OfficialDrawNodeReconciliation).where(OfficialDrawNodeReconciliation.node_id.in_([node.id for node in nodes]))).all() if nodes else []
        by_node = {item.node_id: item for item in reconciliations}
        if not nodes or len(by_node) != len(nodes) or any(item.reconciliation_status != "CANONICAL" or item.match_id is None for item in reconciliations):
            continue
        node_probabilities: list[dict[str, Any]] = []
        for node in nodes:
            match = session.get(Match, by_node[node.id].match_id)
            if not match or match.participant_1_id not in ratings or match.participant_2_id not in ratings:
                continue
            probability = _elo_probability(ratings[match.participant_1_id], ratings[match.participant_2_id])
            node_probabilities.append({
                "source_node_key": node.source_node_key,
                "canonical_match_id": match.id,
                "participant_1_id": match.participant_1_id,
                "participant_2_id": match.participant_2_id,
                "participant_1_win_probability_bps": round(probability * 10000),
                "participant_2_win_probability_bps": 10000 - round(probability * 10000),
            })
        if len(node_probabilities) != len(nodes):
            continue
        session.add(TournamentSimulationSnapshot(
            model_snapshot_id=model.id,
            tournament_id=tournament.id,
            draw_topology_id=topology.id,
            input_cutoff=model.training_cutoff,
            simulation_status="PUBLISHED",
            simulation_count=settings.modeling_simulation_count,
            probability_payload={
                "method": "deterministic_independent_draw-node_simulation",
                "node_win_probabilities": node_probabilities,
                "note": "Probabilities are independently evaluated for each canonically reconciled draw node; bracket advancement is represented by the official topology and node IDs.",
            },
            provenance={
                "calendar_entry_id": entry.id,
                "document_id": document.id,
                "document_content_hash": document.content_hash,
                "topology_id": topology.id,
                "model_key": model.model_key,
                "model_version": model.model_version,
            },
        ))
        created += 1
    return created


def run_model_pipeline(session: Session, settings: Settings | None = None) -> dict[str, int | str]:
    """Train/evaluate and publish only outputs whose evidence prerequisites are satisfied."""
    settings = settings or get_settings()
    confirmed_ids = _confirmed_participant_ids(session)
    matches = _training_matches(session, confirmed_ids)
    ratings, evaluation = _evaluate_and_fit(matches)
    model = _upsert_model(session, matches, ratings, evaluation)
    if model is None:
        return {"status": "insufficient_training_data", "confirmed_participants": len(confirmed_ids), "training_matches": len(matches)}
    forecasts = _publish_forecasts(session, model, ratings, settings)
    h2h = _publish_h2h_snapshots(session, confirmed_ids, matches)
    simulations = _publish_simulations(session, model, ratings, settings)
    return {
        "status": "ok",
        "model_snapshot_id": model.id,
        "confirmed_participants": len(confirmed_ids),
        "training_matches": len(matches),
        "forecasts_published": forecasts,
        "head_to_head_snapshots_published": h2h,
        "simulations_published": simulations,
    }
