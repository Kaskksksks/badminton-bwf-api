from datetime import date, datetime, timedelta, timezone

from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from app.core.config import Settings
from app.db.base import Base
from app.db.models import (
    Event,
    HeadToHeadSnapshot,
    Match,
    MatchForecastSnapshot,
    ModelSnapshot,
    Participant,
    ParticipantMember,
    Player,
    Tournament,
)
from app.modeling.service import model_readiness, run_model_pipeline


def make_session():
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, expire_on_commit=False)


def add_fixture(session, *, category: str = "HSBC BWF World Tour Super 500"):
    tournament = Tournament(
        name="BWF World Tour Test",
        source_name_raw="BWF World Tour Test",
        source_category_raw=category,
        start_date=date(2026, 1, 1),
        end_date=date(2026, 1, 7),
        status="COMPLETED",
    )
    session.add(tournament)
    session.flush()
    event = Event(tournament_id=tournament.id, event_type="MS")
    session.add(event)
    players = [
        Player(full_name="Confirmed One", identity_status="CONFIRMED"),
        Player(full_name="Confirmed Two", identity_status="CONFIRMED"),
    ]
    session.add_all(players)
    session.flush()
    participants = []
    for player in players:
        participant = Participant(
            participant_kind="SINGLES",
            canonical_member_hash=f"hash-{player.id}",
            display_name=player.full_name,
            identity_resolution_status="CONFIRMED",
        )
        session.add(participant)
        session.flush()
        session.add(ParticipantMember(participant_id=participant.id, player_id=player.id, member_order=1))
        participants.append(participant)
    session.flush()
    for index in range(10):
        session.add(Match(
            source_match_key=f"fixture-{index}",
            match_date=date(2026, 1, 1) + timedelta(days=index),
            tournament_id=tournament.id,
            event_id=event.id,
            status="COMPLETED",
            participant_1_id=participants[0].id,
            participant_2_id=participants[1].id,
            winner_participant_id=participants[index % 2].id,
            score_validation_status="VALID",
            completion_basis="FIXTURE",
            source_completeness="COMPLETE",
        ))
    scheduled = Match(
        source_match_key="scheduled-fixture",
        match_date=date(2026, 12, 1),
        scheduled_time=datetime(2026, 12, 1, 10, tzinfo=timezone.utc),
        tournament_id=tournament.id,
        event_id=event.id,
        status="SCHEDULED",
        participant_1_id=participants[0].id,
        participant_2_id=participants[1].id,
        score_validation_status="PENDING",
        completion_basis="FIXTURE",
        source_completeness="COMPLETE",
    )
    session.add(scheduled)
    session.flush()
    return tournament, participants, scheduled


def test_model_pipeline_publishes_evaluated_model_h2h_and_forecast():
    factory = make_session()
    with factory.begin() as session:
        tournament, participants, scheduled = add_fixture(session)
        summary = run_model_pipeline(session, Settings(modeling_max_forecasts_per_run=10))
        model = session.scalar(select(ModelSnapshot).where(ModelSnapshot.model_status == "ACTIVE"))
        h2h = session.scalar(select(HeadToHeadSnapshot).where(HeadToHeadSnapshot.summary_status == "VALIDATED"))
        forecast = session.scalar(select(MatchForecastSnapshot).where(MatchForecastSnapshot.match_id == scheduled.id))

    assert summary["status"] == "ok"
    assert model is not None
    assert model.calibration_status == "EVALUATED"
    assert h2h is not None
    assert h2h.eligible_meetings == 10
    assert forecast is not None
    assert forecast.forecast_status == "PUBLISHED"
    assert forecast.participant_1_win_probability_bps + forecast.participant_2_win_probability_bps == 10000


def test_model_readiness_reports_real_corpus_counts_without_writing_snapshots():
    factory = make_session()
    with factory.begin() as session:
        add_fixture(session)
        readiness = model_readiness(session)
        snapshots = session.scalars(select(ModelSnapshot)).all()

    assert readiness["publication_ready"] is True
    assert readiness["approved_dated_validated_completed_matches"] == 10
    assert readiness["confirmed_participants"] == 2
    assert readiness["write_side_effects"] is False
    assert snapshots == []


def test_model_pipeline_excludes_non_target_senior_tournament_history():
    factory = make_session()
    with factory.begin() as session:
        add_fixture(session, category="International Challenge")
        summary = run_model_pipeline(session, Settings(modeling_max_forecasts_per_run=10))
        model = session.scalar(select(ModelSnapshot).where(ModelSnapshot.model_status == "ACTIVE"))

    assert summary["status"] == "insufficient_training_data"
    assert summary["training_matches"] == 0
    assert model is None
