from __future__ import annotations

import httpx
import pytest

from app.core.config import Settings
from app.db.models import Player, PlayerAlias, PlayerProfileSnapshot
from app.ingestion.player_profiles.service import (
    BWFPlayerProfileClient,
    Candidate,
    SourceAccessStopped,
    decide_alias,
    ensure_collection_allowed,
    extract_candidates,
    extract_profile,
    normalize_name,
)


def enabled_settings(**changes: object) -> Settings:
    values: dict[str, object] = {
        "bwf_player_profiles_enabled": True,
        "bwf_player_profiles_allow_live_source": True,
        "bwf_player_profiles_permission_reference": "authorised-test-reference",
        "bwf_player_profiles_min_request_interval_seconds": 1,
    }
    values.update(changes)
    return Settings(**values)


def profile_snapshot(profile_id: str = "58240", name: str = "Yuta Watanabe", country: str = "JPN") -> PlayerProfileSnapshot:
    return PlayerProfileSnapshot(
        id="snapshot-1", source_id="source-1", bwf_profile_id=profile_id, source_url=f"https://bwfbadminton.com/player/{profile_id}",
        content_hash="hash", profile_name=name, country_code=country, payload={}, parser_version="test",
    )


def test_normalises_aliases_without_diacritics() -> None:
    assert normalize_name("  José  Pérez-Smith ") == "JOSE PEREZ SMITH"


def test_extracts_observed_search_candidates() -> None:
    candidates = extract_candidates([{"id": 58240, "name_display": "YUTA WATANABE", "nationality_item": {"code_iso3": "JPN"}}])
    assert candidates == [Candidate("58240", "YUTA WATANABE", "JPN")]


def test_extracts_observed_bold_search_name_and_flag_country_code() -> None:
    candidates = extract_candidates([{
        "id": 54360,
        "name_display_bold": '<span class="name-2">JOO</span> <span class="name-1">Eun Ae</span>',
        "nationality_item": {"name": "Korea", "flag_url_thumbnail": "https://img.bwfbadminton.com/image/upload/v2/assets/flag-circle-svg-custom/KOR.png"},
    }])
    assert candidates == [Candidate("54360", "JOO Eun Ae", "KOR")]


def test_extracts_official_profile_summary() -> None:
    profile = extract_profile({"results": {"id": 58240, "name_display": "Yuta Watanabe", "date_of_birth": "1997-06-13", "nationality": "JPN", "country_model": {"code_iso3": "JPN", "name": "Japan"}, "profile_type": "PLAYER"}})
    assert profile["bwf_profile_id"] == "58240"
    assert profile["country_code"] == "JPN"
    assert str(profile["date_of_birth"]) == "1997-06-13"


def test_unique_exact_profile_is_automatic_confirmation() -> None:
    alias = PlayerAlias(id="alias-1", source_id="historical", alias_text="YUTA WATANABE", normalized_alias="YUTA WATANABE")
    player = Player(id="player-1", full_name="Yuta Watanabe", country_code="JPN")
    decision = decide_alias(alias, player, profile_snapshot(), exact_candidate_count=1)
    assert decision[0] == "CONFIRMED_AUTO"
    assert decision[1] == "UNIQUE_EXACT_NAME"
    assert decision[2] == 80


def test_observed_bold_search_candidate_can_pass_country_consistency() -> None:
    alias = PlayerAlias(id="alias-1", source_id="historical", alias_text="JOO Eun Ae", normalized_alias="JOO EUN AE")
    player = Player(id="player-1", full_name="JOO Eun Ae", country_code="KOR")
    decision = decide_alias(alias, player, profile_snapshot(name="JOO Eun Ae", country="KOR"), exact_candidate_count=1, search_country_code="KOR")
    assert decision[0] == "CONFIRMED_AUTO"


def test_country_mismatch_is_conflicted_and_not_confirmed() -> None:
    alias = PlayerAlias(id="alias-1", source_id="historical", alias_text="YUTA WATANABE", normalized_alias="YUTA WATANABE")
    player = Player(id="player-1", full_name="Yuta Watanabe", country_code="JPN")
    decision = decide_alias(alias, player, profile_snapshot(), exact_candidate_count=1, search_country_code="KOR")
    assert decision[0] == "CONFLICTED"
    assert decision[1] == "COUNTRY_MISMATCH"


def test_collision_is_conflicted_and_not_confirmed() -> None:
    alias = PlayerAlias(id="alias-1", source_id="historical", alias_text="YUTA WATANABE", normalized_alias="YUTA WATANABE")
    player = Player(id="player-1", full_name="Yuta Watanabe", country_code="JPN")
    decision = decide_alias(alias, player, profile_snapshot(), exact_candidate_count=2)
    assert decision[0] == "CONFLICTED"
    assert decision[1] == "MULTIPLE_CANDIDATES"


def test_name_mismatch_cannot_be_linked() -> None:
    alias = PlayerAlias(id="alias-1", source_id="historical", alias_text="YUTA WATANABE", normalized_alias="YUTA WATANABE")
    player = Player(id="player-1", full_name="Kento Momota", country_code="JPN")
    assert decide_alias(alias, player, profile_snapshot(name="Kento Momota"), 1)[0] == "UNRESOLVED"


def test_disabled_profile_source_gate_fails_before_network() -> None:
    with pytest.raises(RuntimeError, match="disabled"):
        ensure_collection_allowed(Settings())


def test_permission_gate_requires_reference_when_enabled() -> None:
    with pytest.raises(ValueError, match="PERMISSION_REFERENCE"):
        Settings(bwf_player_profiles_enabled=True, bwf_player_profiles_allow_live_source=True)


def test_access_denial_stops_without_retrying() -> None:
    transport = httpx.MockTransport(lambda request: httpx.Response(403, request=request, json={"detail": "denied"}))
    client = BWFPlayerProfileClient(enabled_settings(), httpx.Client(base_url="https://example.test", transport=transport))
    with pytest.raises(SourceAccessStopped, match="HTTP 403"):
        client.search("YUTA WATANABE")


def test_only_two_fixed_endpoint_methods_are_exposed() -> None:
    assert not hasattr(BWFPlayerProfileClient, "get_url")
    assert set(name for name in dir(BWFPlayerProfileClient) if not name.startswith("_")) >= {"search", "summary", "close"}


def test_no_historical_match_import_or_mutation_symbols() -> None:
    import app.ingestion.player_profiles.service as service
    assert not hasattr(service, "Match")
    assert not hasattr(service, "MatchGame")


def test_youth_profile_type_is_preserved() -> None:
    profile = extract_profile({"results": {"id": 1, "name_display": "Junior Player", "country_model": {"code_iso3": "MAS"}, "profile_type": "JUNIOR"}})
    assert profile["profile_type"] == "JUNIOR"
