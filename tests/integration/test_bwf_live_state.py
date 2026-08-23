from __future__ import annotations

from datetime import datetime, timezone

import httpx
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from app.core.config import Settings
from app.db.base import Base
from app.db.models import DataSource, GameIntervalAssessment, Match, MatchGame, RawIngestionRecord, SourceKind
from app.ingestion.adapters.bwf.client import BWFClient
from app.snapshots.service import record_game_state


def test_bwf_client_calls_verified_current_live_route() -> None:
    seen: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(str(request.url))
        return httpx.Response(200, json={"results": []})

    client = BWFClient(
        Settings(bwf_live_base_url="https://example.test"),
        client=httpx.Client(transport=httpx.MockTransport(handler), base_url="https://example.test"),
    )
    response = client.list_current_tournaments()
    assert response.endpoint_key == "vue-current-live"
    assert seen == ["https://example.test/api/match-center/vue-current-live"]


def test_game_state_observations_are_deduplicated_and_interval_is_not_claimed_exact() -> None:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    with factory.begin() as session:
        source = DataSource(code="BWF_LIVE", source_kind=SourceKind.BWF_LIVE.value, display_name="BWF")
        session.add(source)
        session.flush()
        raw = RawIngestionRecord(
            source_id=source.id,
            endpoint_key="vue-live-matches",
            content_hash="test",
            raw_payload={"results": []},
            parser_version="test",
            processing_status="CAPTURED",
        )
        session.add(raw)
        session.flush()
        match = Match(
            source_match_key="BWF_LIVE:test-match",
            status="LIVE",
            completion_basis="BWF_OFFICIAL_RESPONSE",
            source_completeness="PARTIAL",
        )
        session.add(match)
        session.flush()
        game = MatchGame(match_id=match.id, game_number=1, status="LIVE", parse_confidence="SOURCE_ASSERTED")
        session.add(game)
        session.flush()
        observed_at = datetime(2026, 8, 23, 10, 0, tzinfo=timezone.utc)
        first = record_game_state(
            session,
            match_id=match.id,
            game_number=1,
            participant_1_score=11,
            participant_2_score=8,
            match_status="LIVE",
            raw_record=raw,
            observed_at=observed_at,
        )
        second = record_game_state(
            session,
            match_id=match.id,
            game_number=1,
            participant_1_score=11,
            participant_2_score=8,
            match_status="LIVE",
            raw_record=raw,
            observed_at=observed_at,
        )
        assert first is not None
        assert second is None
        assessment = session.scalar(select(GameIntervalAssessment).where(GameIntervalAssessment.game_id == game.id))
        assert assessment is not None
        assert assessment.detection_method == "OBSERVED_EXACT_SCORE"
        assert assessment.interval_exact is False
        assert assessment.interval_observed_at is not None
        assert assessment.interval_observed_at.replace(tzinfo=timezone.utc) == observed_at
        assert assessment.interval_source_at is None
