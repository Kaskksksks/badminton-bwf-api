from __future__ import annotations

from datetime import date
from typing import Any

from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from app.core.config import Settings
from app.db.base import Base
from app.db.models import Match, Player, Tournament
from app.ingestion.adapters.bwf.client import BWFResponse
from app.ingestion.adapters.bwf.eligibility import is_paralympic_match, is_paralympic_tournament
from app.ingestion.adapters.bwf.service import synchronize_current_bwf


def _response(endpoint_key: str, payload: dict[str, Any]) -> BWFResponse:
    return BWFResponse(
        endpoint_key=endpoint_key,
        url=f"https://example.test/{endpoint_key}",
        status_code=200,
        payload=payload,
    )


def _match(match_id: int, event: str, player_prefix: str) -> dict[str, Any]:
    return {
        "live_detail": {
            "event": event,
            "match_state": "live",
            "round": "R32",
            "court_code": "1",
            "team1_g1_score": 21,
            "team2_g1_score": 18,
        },
        "match_detail": {
            "id": match_id,
            "t1p1_player_model": {"id": f"{player_prefix}-1", "fullName": f"{player_prefix} One"},
            "t2p1_player_model": {"id": f"{player_prefix}-2", "fullName": f"{player_prefix} Two"},
        },
    }


class FakeBWFClient:
    def __init__(self) -> None:
        self.live_tournament_ids: list[int] = []

    def list_current_tournaments(self) -> BWFResponse:
        return _response(
            "vue-current-live",
            {
                "results": [
                    {"id": 10, "name": "Para Badminton International"},
                    {"id": 20, "name": "European Junior Championships"},
                    {"id": 30, "name": "Continental Senior Championships"},
                ]
            },
        )

    def list_live_matches(self, tournament_id: int) -> BWFResponse:
        self.live_tournament_ids.append(tournament_id)
        if tournament_id == 20:
            results = [_match(2001, "WD-U19", "Junior")]
        elif tournament_id == 30:
            results = [
                _match(3001, "WH1", "Para"),
                _match(3002, "MS", "Senior"),
                _match(3003, "WD-U19", "Junior Event"),
            ]
        else:  # A failure here proves the Para tournament should have been skipped before the request.
            raise AssertionError("Para tournament must not be fetched")
        return _response("vue-live-matches", {"results": results})


def test_paralympic_markers_are_limited_to_competition_metadata() -> None:
    assert is_paralympic_tournament({"name": "Para Badminton International"}) is True
    assert is_paralympic_tournament({"name": "Para International"}) is True
    assert is_paralympic_tournament({"name": "2026 European Junior Championships"}) is False
    assert is_paralympic_tournament({"name": "Senior Continental Championships"}) is False
    assert is_paralympic_match({"live_detail": {"event": "WH1"}}) is True
    assert is_paralympic_match({"live_detail": {"event": "WD-U19"}}) is False
    assert is_paralympic_match({"live_detail": {"event": "MS"}}) is False


def test_live_ingestion_excludes_para_and_junior_boundaries_but_keeps_senior() -> None:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    client = FakeBWFClient()
    settings = Settings(bwf_ingestion_start_date=date(2026, 8, 23))

    with factory.begin() as session:
        result = synchronize_current_bwf(session, client=client, settings=settings)
        tournament_names = set(session.scalars(select(Tournament.name)).all())
        match_keys = set(session.scalars(select(Match.source_match_key)).all())
        player_names = set(session.scalars(select(Player.full_name)).all())

    # Tournament 20 must be filtered before its match endpoint is called.
    assert client.live_tournament_ids == [30]
    assert result == {
        "status": "ok",
        "tournaments": 1,
        "live_matches": 1,
        "skipped_paralympic_tournaments": 1,
        "skipped_paralympic_matches": 1,
        "skipped_junior_tournaments": 1,
        "skipped_junior_matches": 1,
    }
    assert tournament_names == {"Continental Senior Championships"}
    assert match_keys == {"BWF_LIVE:3002"}
    assert player_names == {"Senior One", "Senior Two"}
