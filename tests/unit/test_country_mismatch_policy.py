from __future__ import annotations

import pytest

from app.ingestion.player_profiles.country_mismatch import (
    COUNTRY_MISMATCH_POLICY_VERSION,
    MANUAL_OVERRIDE_POLICY_VERSION,
    canonical_iso3,
    evaluate_country_mismatch_evidence,
)


@pytest.mark.parametrize(
    ("search_code", "profile_code", "canonical"),
    [
        ("MYS", "MAS", "MYS"),
        ("ARE", "UAE", "ARE"),
        ("DEU", "GER", "DEU"),
        ("PHL", "PHI", "PHL"),
        ("TWN", "TPE", "TWN"),
        ("IDN", "INA", "IDN"),
    ],
)
def test_documented_iso_bwf_ioc_country_equivalences_are_auto_eligible(
    search_code: str, profile_code: str, canonical: str
) -> None:
    result = evaluate_country_mismatch_evidence(
        {
            "search_country_code": search_code,
            "official_profile_bwf_nationality_code": profile_code,
        }
    )

    assert result.disposition == "AUTO_EQUIVALENT_ELIGIBLE"
    assert result.canonical_search_country == canonical
    assert result.canonical_profile_country == canonical
    assert result.policy_version == COUNTRY_MISMATCH_POLICY_VERSION
    assert result.manual_override_pair is None


@pytest.mark.parametrize(
    ("search_code", "profile_code", "pair"),
    [
        ("AIN", "RUS", "AIN:RUS"),
        ("RUS", "AIN", "AIN:RUS"),
        ("ENG", "GBR", "ENG:GBR"),
        ("GBR", "ENG", "ENG:GBR"),
    ],
)
def test_user_directed_special_designations_are_explicit_manual_overrides(
    search_code: str, profile_code: str, pair: str
) -> None:
    result = evaluate_country_mismatch_evidence(
        {
            "search_country_code": search_code,
            "official_profile_bwf_nationality_code": profile_code,
        }
    )

    assert result.disposition == "MANUAL_OVERRIDE_ELIGIBLE"
    assert result.reason_code == "USER_DIRECTED_SPECIAL_DESIGNATION_OVERRIDE"
    assert result.manual_override_pair == pair
    assert result.policy_version == MANUAL_OVERRIDE_POLICY_VERSION


@pytest.mark.parametrize(
    ("search_code", "profile_code"),
    [
        ("MAS", "AUS"),
        ("AIN", "GBR"),
        ("ENG", "RUS"),
        ("ZZZ", "YYY"),
        (None, "MAS"),
        ("MYS", None),
    ],
)
def test_unapproved_or_incomplete_country_pairs_remain_conflicted(
    search_code: str | None, profile_code: str | None
) -> None:
    result = evaluate_country_mismatch_evidence(
        {
            "search_country_code": search_code,
            "official_profile_bwf_nationality_code": profile_code,
        }
    )

    assert result.disposition == "REMAIN_CONFLICTED"
    assert result.manual_override_pair is None


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("MYS", "MYS"),
        ("MAS", "MYS"),
        ("DEU", "DEU"),
        ("GER", "DEU"),
        ("AIN", None),
        ("ENG", None),
    ],
)
def test_canonicalisation_never_guesses_special_or_subnational_codes(raw: str, expected: str | None) -> None:
    assert canonical_iso3(raw) == expected
