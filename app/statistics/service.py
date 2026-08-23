from __future__ import annotations

from collections import defaultdict
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import GameIntervalAssessment, Match, MatchGame


def _game_winner_side(game: MatchGame) -> int | None:
    if game.participant_1_score is None or game.participant_2_score is None:
        return None
    if game.participant_1_score == game.participant_2_score:
        return None
    return 1 if game.participant_1_score > game.participant_2_score else 2


def interval_metrics_for_participant(session: Session, participant_id: str) -> dict[str, Any]:
    """Return coverage-aware metrics; never substitute missing observations with estimates."""
    assessments = session.scalars(
        select(GameIntervalAssessment)
        .where(GameIntervalAssessment.interval_type == "ELEVEN_POINT")
        .where(GameIntervalAssessment.interval_player_participant_id == participant_id)
    ).all()
    result: dict[str, Any] = {
        "participant_id": participant_id,
        "eligible_games": 0,
        "interval_leads": 0,
        "interval_lead_conversions": 0,
        "interval_lead_conversion_rate": None,
        "interval_trailing_games": 0,
        "interval_comebacks": 0,
        "interval_comeback_rate": None,
        "average_comeback_deficit": None,
        "largest_interval_deficit_overcome": None,
        "post_interval_point_differential_sum": 0,
        "derivation_note": "Only game states with a determined interval participant and final scores are eligible.",
    }
    comeback_deficits: list[int] = []
    for assessment in assessments:
        if assessment.participant_1_score is None or assessment.participant_2_score is None:
            continue
        game = session.get(MatchGame, assessment.game_id)
        if not game:
            continue
        match = session.get(Match, game.match_id)
        winner_side = _game_winner_side(game)
        if not match or winner_side is None:
            continue
        if match.participant_1_id == participant_id:
            interval_self, interval_other = assessment.participant_1_score, assessment.participant_2_score
            final_self, final_other = game.participant_1_score, game.participant_2_score
            self_won = winner_side == 1
        elif match.participant_2_id == participant_id:
            interval_self, interval_other = assessment.participant_2_score, assessment.participant_1_score
            final_self, final_other = game.participant_2_score, game.participant_1_score
            self_won = winner_side == 2
        else:
            continue
        result["eligible_games"] += 1
        result["post_interval_point_differential_sum"] += (final_self - final_other) - (interval_self - interval_other)
        if interval_self > interval_other:
            result["interval_leads"] += 1
            if self_won:
                result["interval_lead_conversions"] += 1
        elif interval_self < interval_other:
            result["interval_trailing_games"] += 1
            if self_won:
                result["interval_comebacks"] += 1
                comeback_deficits.append(interval_other - interval_self)

    if result["interval_leads"]:
        result["interval_lead_conversion_rate"] = result["interval_lead_conversions"] / result["interval_leads"]
    if result["interval_trailing_games"]:
        result["interval_comeback_rate"] = result["interval_comebacks"] / result["interval_trailing_games"]
    if comeback_deficits:
        result["average_comeback_deficit"] = sum(comeback_deficits) / len(comeback_deficits)
        result["largest_interval_deficit_overcome"] = max(comeback_deficits)
    return result


def interval_coverage_summary(session: Session) -> dict[str, int]:
    rows = session.scalars(select(GameIntervalAssessment).where(GameIntervalAssessment.interval_type == "ELEVEN_POINT")).all()
    return {
        "interval_assessments": len(rows),
        "observed_exact_score_states": sum(item.detection_method == "OBSERVED_EXACT_SCORE" for item in rows),
        "inferred_crossings": sum(item.detection_method == "INFERRED_CROSSING" for item in rows),
        "undetermined": sum(item.detection_method == "UNDETERMINED" for item in rows),
        "source_exact_events": sum(item.interval_exact for item in rows),
    }
