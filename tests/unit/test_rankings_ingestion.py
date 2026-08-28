from __future__ import annotations

from datetime import date

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.db.base import Base
from app.db.models import RankingEntry, RankingSnapshot
from app.ingestion.rankings.service import RankingScope, SourceResponse, diagnose_ranking_row_shape, normalize_row, synchronize_rankings
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


def test_ranking_shape_diagnostic_returns_keys_without_persisting_rows() -> None:
    result = diagnose_ranking_row_shape(settings=authorised_settings(), client=FakeRankingClient())
    assert result["scope"]["discipline"] == "MS"
    assert result["row_count_on_first_page"] == 1
    assert result["row_keys"] == ["change", "countryCode", "name", "playerId", "points", "rank", "tournaments"]
    assert result["nested_mapping_keys"] == {}


def test_ranking_shape_diagnostic_can_target_an_authorized_senior_discipline() -> None:
    result = diagnose_ranking_row_shape(discipline="XD", settings=authorised_settings(), client=FakeRankingClient())
    assert result["scope"]["discipline"] == "XD"


def test_normalizes_current_bwf_single_and_doubles_model_fields_without_name_inference() -> None:
    singles = normalize_row(
        RankingScope("WORLD", "SENIOR", 2, 6, "MS"),
        {
            "rank": 1,
            "points": 10000,
            "rank_change": 2,
            "player1_id": 99,
            "player1_model": {"id": 99, "name_display_bold": "Source Singles Name"},
            "p1_country_model": {"name": "TST"},
        },
    )
    doubles = normalize_row(
        RankingScope("WORLD", "SENIOR", 2, 6, "MD"),
        {
            "rank": 1,
            "points": 10000,
            "team_id": 88,
            "player1_model": {"id": 11, "name_display_bold": "Source Player One"},
            "player2_model": {"id": 12, "name_display_bold": "Source Player Two"},
            "p1_country_model": {"name": "TST"},
            "p2_country_model": {"name": "TST"},
        },
    )
    assert singles["subject_display_name"] == "Source Singles Name"
    assert singles["official_subject_id"] == "99"
    assert doubles["subject_display_name"] == "Source Player One / Source Player Two"
    assert doubles["official_subject_id"] == "88"
    assert doubles["country_code"] == "TST"


def test_omits_ambiguous_doubles_country_from_current_bwf_model_fields() -> None:
    row = normalize_row(
        RankingScope("WORLD", "SENIOR", 2, 6, "XD"),
        {
            "rank": 1,
            "points": 10000,
            "team_id": 88,
            "player1_model": {"name_display_bold": "Source Player One"},
            "player2_model": {"name_display_bold": "Source Player Two"},
            "p1_country_model": {"name": "AAA"},
            "p2_country_model": {"name": "BBB"},
        },
    )
    assert row["country_code"] is None


def test_scheduler_adds_separate_tuesday_utc_rankings_job(monkeypatch) -> None:
    monkeypatch.setattr(scheduler_module, "get_settings", lambda: authorised_settings())
    scheduler = scheduler_module.build_scheduler()
    job = scheduler.get_job("bwf-rankings-weekly")
    assert job is not None
    assert "day_of_week='tue'" in str(job.trigger)
    assert "hour='12'" in str(job.trigger)
    assert scheduler.get_job("bwf-sync") is not None
