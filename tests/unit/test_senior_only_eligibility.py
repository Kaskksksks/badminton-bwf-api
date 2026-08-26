from app.ingestion.adapters.bwf.eligibility import (
    is_junior_match,
    is_junior_tournament,
    is_paralympic_match,
    is_paralympic_tournament,
)


def test_explicit_junior_tournament_markers_are_excluded() -> None:
    assert is_junior_tournament({"name": "YONEX SUNRISE India Junior International Grand Prix 2026"})
    assert is_junior_tournament({"tournament_type": "U19 International Series"})
    assert is_junior_tournament({"category": "World Junior Championships"})


def test_senior_and_unspecified_youth_tournaments_remain_eligible() -> None:
    assert not is_junior_tournament({"name": "LI-NING China Masters 2026"})
    assert not is_junior_tournament({"name": "BWF Youth Development Festival"})
    assert not is_junior_tournament({"name": "POLYTRON Pontianak Indonesia Masters 2026"})


def test_explicit_junior_event_markers_are_excluded() -> None:
    assert is_junior_match({"live_detail": {"event": "MS-U19"}})
    assert is_junior_match({"match_detail": {"discipline": "XD U-17"}})
    assert is_junior_match({"live_detail": {"event_name": "Junior Women's Singles"}})


def test_senior_and_para_eligibility_remain_distinct() -> None:
    senior = {"live_detail": {"event": "MS"}}
    para = {"live_detail": {"event": "WH1"}}
    assert not is_junior_match(senior)
    assert not is_paralympic_match(senior)
    assert not is_junior_match(para)
    assert is_paralympic_match(para)
    assert not is_paralympic_tournament({"name": "LI-NING China Masters 2026"})
