from __future__ import annotations

import hashlib
import json
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import (
    GameIntervalAssessment,
    GameStateObservation,
    GameTimingFact,
    Match,
    MatchGame,
    MatchStatus,
    RawIngestionRecord,
    TimingBasis,
)

DERIVATION_VERSION = "interval-v1"


def state_hash(payload: dict[str, object]) -> str:
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def record_game_state(
    session: Session,
    *,
    match_id: str,
    game_number: int,
    participant_1_score: int,
    participant_2_score: int,
    match_status: str,
    raw_record: RawIngestionRecord,
    observed_at: datetime,
    court_code: str | None = None,
    service_side: int | None = None,
    source_observed_at: datetime | None = None,
) -> GameStateObservation | None:
    """Store a material observed state once, retaining collection time as evidence."""
    payload = {
        "game": game_number,
        "p1": participant_1_score,
        "p2": participant_2_score,
        "status": match_status,
        "court": court_code,
        "service": service_side,
    }
    digest = state_hash(payload)
    existing = session.scalar(
        select(GameStateObservation).where(
            GameStateObservation.match_id == match_id,
            GameStateObservation.game_number == game_number,
            GameStateObservation.state_hash == digest,
        )
    )
    if existing:
        return None
    observation = GameStateObservation(
        match_id=match_id,
        game_number=game_number,
        observed_at=observed_at,
        source_observed_at=source_observed_at,
        participant_1_score=participant_1_score,
        participant_2_score=participant_2_score,
        match_status=match_status,
        court_code=court_code,
        service_side=service_side,
        raw_record_id=raw_record.id,
        state_hash=digest,
    )
    session.add(observation)
    session.flush()

    game = session.scalar(select(MatchGame).where(MatchGame.match_id == match_id, MatchGame.game_number == game_number))
    if game:
        timing = session.scalar(select(GameTimingFact).where(GameTimingFact.game_id == game.id))
        if timing is None:
            timing = GameTimingFact(
                game_id=game.id,
                timing_basis=TimingBasis.OBSERVATION_BOUND.value,
                first_observed_at=observed_at,
                last_observed_at=observed_at,
                evidence_record_id=raw_record.id,
            )
            session.add(timing)
        else:
            timing.first_observed_at = min(timing.first_observed_at or observed_at, observed_at)
            timing.last_observed_at = max(timing.last_observed_at or observed_at, observed_at)
        session.flush()
        derive_eleven_point_interval(session, game, observation)
    return observation


def derive_eleven_point_interval(session: Session, game: MatchGame, latest: GameStateObservation) -> GameIntervalAssessment:
    """Derive only facts supported by stored observations; never create a rally timestamp."""
    assessment = session.scalar(
        select(GameIntervalAssessment).where(
            GameIntervalAssessment.game_id == game.id,
            GameIntervalAssessment.interval_type == "ELEVEN_POINT",
            GameIntervalAssessment.derivation_version == DERIVATION_VERSION,
        )
    )
    p1, p2 = latest.participant_1_score, latest.participant_2_score
    method = "UNDETERMINED"
    confidence = "LOW"
    interval_side: str | None = None
    interval_p1: int | None = None
    interval_p2: int | None = None
    observed_at: datetime | None = None

    # Exact observed score state: the side at 11 while the opponent is <=10.
    # The collection timestamp is still an observation time, not the rally time.
    if p1 == 11 and p2 <= 10:
        method, confidence, interval_side, interval_p1, interval_p2, observed_at = (
            "OBSERVED_EXACT_SCORE", "HIGH", "P1", p1, p2, latest.observed_at
        )
    elif p2 == 11 and p1 <= 10:
        method, confidence, interval_side, interval_p1, interval_p2, observed_at = (
            "OBSERVED_EXACT_SCORE", "HIGH", "P2", p1, p2, latest.observed_at
        )
    elif max(p1, p2) > 11:
        method, confidence, observed_at = "INFERRED_CROSSING", "LOW", latest.observed_at

    if assessment is None:
        assessment = GameIntervalAssessment(
            game_id=game.id,
            interval_type="ELEVEN_POINT",
            derivation_version=DERIVATION_VERSION,
            detection_method=method,
            confidence=confidence,
            interval_exact=False,
            evidence_observation_id=latest.id,
        )
        session.add(assessment)
    # Do not replace a high-confidence direct observed interval with later, weaker crossings.
    if assessment.detection_method in {"UNDETERMINED", "INFERRED_CROSSING"} or method == "OBSERVED_EXACT_SCORE":
        match = session.get(Match, game.match_id)
        assessment.detection_method = method
        assessment.confidence = confidence
        assessment.interval_exact = False
        assessment.interval_player_participant_id = (
            match.participant_1_id if method == "OBSERVED_EXACT_SCORE" and interval_side == "P1" and match else
            match.participant_2_id if method == "OBSERVED_EXACT_SCORE" and interval_side == "P2" and match else
            None
        )
        assessment.participant_1_score = interval_p1
        assessment.participant_2_score = interval_p2
        assessment.interval_observed_at = observed_at
        assessment.interval_source_at = None
        assessment.evidence_observation_id = latest.id
    session.flush()
    return assessment
