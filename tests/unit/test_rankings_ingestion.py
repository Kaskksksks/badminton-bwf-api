from __future__ import annotations

from datetime import date

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.db.base import Base
from app.db.models import RankingEntry, RankingSnapshot
from app.ingestion.rankings.service import SourceResponse, synchronize_rankings
from app.polling import scheduler as scheduler_module


class FakeRankingClient:
    def __init__(self) -> None:
        self.closed = False

    def close(self) -> None:
        self.closed = True

    def get_weeks(self, ranking_id: int) -> SourceResponse:
        return SourceResponse(
            endpoint_key="vue-rankingweek",
            url=f"https://example.test/api/vue-rankingweek?rankId={ranking_id}",
            status_code=200,
            payload=[{"publicationId": 101, "effectiveDate": "2026-08-18", "label": "Week 34"}],
        )

    def get_table(self, scope, publication_id: int, page: int, draw_count: int) -> SourceResponse:
        assert publication_id == 101
        assert page == 1
        return SourceResponse(
            endpoint_key="vue-rankingtable",
            url=(
                "https://example.test/api/vue-rankingtable?"
                f"rankId={scope.ranking_id}&catId={scope.category_id}&publicationId={publication_id}"
            ),
            status_code=200,
            payload={
                "results": {
                    "data": [
                        {
                            "rank": 1,
                            "points": 10000,
                            "tournaments": 10,
                            "change": 0,
                            "playerId": f"{scope.ranking_id}-{scope.category_id}-1",
                            "name": f"{scope.ranking_system} {scope.discipline} player",
                            "countryCode": "TST",
                        }
                    ],
                    "last_page": 1,
                }
            },
        )


def authorised_settings(**overrides) -> Settings:
    values = {
        "database_url": "sqlite+pysqlite:///:memory:",
        "bwf_rankings_enabled": True,
        "bwf_rankings_allow_live_source": True,
        "bwf_rankings_permission_reference": "TEST-PERMISSION-REFERENCE",
        "bwf_rankings_scheduler_enabled": True,
    }
    values.update(overrides)
    return Settings(**values)


def test_imports_all_requested_scopes_and_is_idempotent() -> None:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    settings = authorised_settings()
    with Session(engine) as session:
        first = synchronize_rankings(session, settings=settings, client=FakeRankingClient())
        session.commit()
        assert first["created_scopes"] == 10
        assert first["accepted_entries"] == 10
        assert session.scalar(select(RankingSnapshot).where(RankingSnapshot.ranking_system == "WORLD_JUNIOR")) is None
        assert len(session.scalars(select(RankingEntry)).all()) == 10

        second = synchronize_rankings(session, settings=settings, client=FakeRankingClient())
        session.commit()
        assert second["created_scopes"] == 0
        assert second["duplicate_scopes"] == 10
        assert len(session.scalars(select(RankingSnapshot)).all()) == 10


def test_live_collection_is_refused_without_explicit_enablement() -> None:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        with pytest.raises(RuntimeError, match="collection is disabled"):
            synchronize_rankings(session, settings=Settings(database_url="sqlite+pysqlite:///:memory:"), client=FakeRankingClient())


def test_scheduler_adds_separate_tuesday_utc_rankings_job(monkeypatch) -> None:
    monkeypatch.setattr(scheduler_module, "get_settings", lambda: authorised_settings())
    scheduler = scheduler_module.build_scheduler()
    job = scheduler.get_job("bwf-rankings-weekly")
    assert job is not None
    assert "day_of_week='tue'" in str(job.trigger)
    assert "hour='12'" in str(job.trigger)
    assert scheduler.get_job("bwf-sync") is not None
