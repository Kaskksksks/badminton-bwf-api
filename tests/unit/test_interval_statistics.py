from __future__ import annotations

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.db.base import Base
from app.db.models import GameIntervalAssessment, Match, MatchGame, Participant
from app.statistics.service import interval_metrics_for_participant


def test_interval_lead_conversion_is_computed_only_for_eligible_game() -> None:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    with factory.begin() as session:
        p1 = Participant(participant_kind="SINGLES", canonical_member_hash="p1", display_name="P1")
        p2 = Participant(participant_kind="SINGLES", canonical_member_hash="p2", display_name="P2")
        session.add_all([p1, p2])
        session.flush()
        match = Match(
            source_match_key="stats-match",
            status="COMPLETED",
            participant_1_id=p1.id,
            participant_2_id=p2.id,
            completion_basis="BWF_OFFICIAL_RESPONSE",
            source_completeness="COMPLETE",
        )
        session.add(match)
        session.flush()
        game = MatchGame(
            match_id=match.id,
            game_number=1,
            participant_1_score=21,
            participant_2_score=15,
            status="COMPLETED",
            parse_confidence="SOURCE_ASSERTED",
        )
        session.add(game)
        session.flush()
        session.add(
            GameIntervalAssessment(
                game_id=game.id,
                interval_type="ELEVEN_POINT",
                interval_player_participant_id=p1.id,
                participant_1_score=11,
                participant_2_score=8,
                interval_exact=False,
                detection_method="OBSERVED_EXACT_SCORE",
                confidence="HIGH",
                derivation_version="test",
            )
        )
        session.flush()
        metrics = interval_metrics_for_participant(session, p1.id)
        assert metrics["eligible_games"] == 1
        assert metrics["interval_leads"] == 1
        assert metrics["interval_lead_conversions"] == 1
        assert metrics["interval_lead_conversion_rate"] == 1.0
