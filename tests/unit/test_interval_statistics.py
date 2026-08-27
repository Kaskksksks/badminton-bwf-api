from __future__ import annotations

from datetime import date

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.api.v1.routes import get_player_statistics
from app.db.base import Base
from app.db.models import DataSource, Event, GameIntervalAssessment, Match, MatchGame, MatchParticipantContext, Participant, ParticipantMember, Player, PlayerAlias, Tournament
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


def test_confirmed_active_player_statistics_publish_only_stored_eligible_intervals() -> None:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    with factory.begin() as session:
        tournament = Tournament(name="Approved", source_name_raw="Approved", source_category_raw="HSBC BWF World Tour Super 500", status="ACTIVE")
        session.add(tournament)
        session.flush()
        event = Event(tournament_id=tournament.id, event_type="MS", category="HSBC BWF World Tour Super 500")
        player = Player(full_name="Confirmed Player", identity_status="CONFIRMED")
        source = DataSource(code="TEST_BWF_PROFILE_SOURCE", source_kind="BWF_PLAYER_PROFILES", display_name="Test BWF profiles", base_url="https://example.invalid")
        session.add_all([event, player, source])
        session.flush()
        alias = PlayerAlias(player_id=player.id, source_id=source.id, alias_text="Confirmed Player", normalized_alias="CONFIRMED PLAYER", resolution_status="CONFIRMED")
        session.add(alias)
        session.flush()
        p1 = Participant(participant_kind="SINGLES", canonical_member_hash="confirmed-player", display_name="Confirmed Player", identity_resolution_status="CONFIRMED")
        p2 = Participant(participant_kind="SINGLES", canonical_member_hash="opponent", display_name="Opponent", identity_resolution_status="UNRESOLVED")
        session.add_all([p1, p2])
        session.flush()
        session.add(ParticipantMember(participant_id=p1.id, player_id=player.id, source_alias_id=alias.id, member_order=1))
        match = Match(source_match_key="stats-active-player", match_date=date.today(), tournament_id=tournament.id, event_id=event.id, status="COMPLETED", participant_1_id=p1.id, participant_2_id=p2.id, winner_participant_id=p1.id, completion_basis="BWF_OFFICIAL_RESPONSE", source_completeness="COMPLETE")
        session.add(match)
        session.flush()
        session.add(MatchParticipantContext(match_id=match.id, participant_id=p1.id, side=1))
        game = MatchGame(match_id=match.id, game_number=1, participant_1_score=21, participant_2_score=15, status="COMPLETED", parse_confidence="SOURCE_ASSERTED")
        session.add(game)
        session.flush()
        session.add(GameIntervalAssessment(game_id=game.id, interval_type="ELEVEN_POINT", interval_player_participant_id=p1.id, participant_1_score=11, participant_2_score=8, interval_exact=True, detection_method="OBSERVED_EXACT_SCORE", confidence="HIGH", derivation_version="test"))
        session.flush()
        payload = get_player_statistics(player.id, session)

    assert payload["data"]["trusted_statistics_eligible"] is True
    assert len(payload["data"]["statistics"]) == 1
    assert payload["data"]["statistics"][0]["eligible_games"] == 1
    assert payload["data"]["statistics"][0]["interval_lead_conversion_rate"] == 1.0
    assert payload["meta"]["source"] == "BWF_LIVE_DERIVED"
