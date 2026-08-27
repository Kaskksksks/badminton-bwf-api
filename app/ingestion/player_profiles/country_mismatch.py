"""Pure country-code comparison and manual-override policy for identity review.

This module never contacts BWF, queries a database, or writes a link.  It preserves
raw evidence and returns an explicit disposition for a caller to audit or apply.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, Mapping


COUNTRY_MISMATCH_POLICY_VERSION = "country-mismatch-review-v1"
MANUAL_OVERRIDE_POLICY_VERSION = "country-mismatch-manual-override-v1"

# These are direct ISO 3166-1 alpha-3 to BWF/IOC display-code equivalences.  The
# mapping is intentionally explicit and one-to-one; unknown values are not inferred.
ISO3_TO_BWF_IOC: dict[str, str] = {
    "DZA": "ALG", "AGO": "ANG", "BFA": "BUR", "TCD": "CHA", "COG": "CGO",
    "CIV": "CIV", "GMB": "GAM", "GIN": "GUI", "GNB": "GBS", "GNQ": "GEQ",
    "LSO": "LES", "LBY": "LBA", "MDG": "MAD", "MWI": "MAW", "MUS": "MRI",
    "MRT": "MTN", "NER": "NIG", "NGA": "NGR", "ZAF": "RSA", "TZA": "TAN",
    "ZMB": "ZAM", "ATG": "ANT", "ABW": "ARU", "BHS": "BAH", "BRB": "BAR",
    "BLZ": "BIZ", "BMU": "BER", "CHL": "CHI", "DOM": "DOM", "DMA": "DMA",
    "SLV": "ESA", "GRD": "GRN", "GTM": "GUA", "HTI": "HAI", "HND": "HON",
    "NIC": "NCA", "PRY": "PAR", "PRI": "PUR", "KNA": "SKN", "VCT": "VIN",
    "URY": "URU", "VEN": "VEN", "VGB": "IVB", "VIR": "ISV", "BHR": "BRN",
    "BGD": "BAN", "BTN": "BHU", "BRN": "BRU", "KHM": "CAM", "IDN": "INA",
    "IRN": "IRI", "KWT": "KUW", "MYS": "MAS", "MNG": "MGL", "MMR": "MYA",
    "NPL": "NEP", "OMN": "OMA", "PSE": "PLE", "PHL": "PHI", "SAU": "KSA",
    "LKA": "SRI", "TWN": "TPE", "THA": "THA", "VNM": "VIE", "ARE": "UAE",
    "ALB": "ALB", "AUT": "AUT", "BGR": "BUL", "HRV": "CRO", "DNK": "DEN",
    "DEU": "GER", "GRC": "GRE", "HUN": "HUN", "ISL": "ISL", "ITA": "ITA",
    "XKX": "KOS", "LVA": "LAT", "LTU": "LTU", "MCO": "MON", "NLD": "NED",
    "NOR": "NOR", "PRT": "POR", "ROU": "ROU", "SMR": "SMR", "SVN": "SLO",
    "SWE": "SWE", "CHE": "SUI", "TUR": "TUR", "ASM": "ASA", "FJI": "FIJ",
    "SLB": "SOL", "WSM": "SAM", "TON": "TGA", "VUT": "VAN",
}

# A raw three-letter value can be syntactically valid in more than one code scheme.
# Therefore country identity is determined from an explicit *pair*, never from a
# reverse lookup of one raw value in isolation.
DOCUMENTED_EQUIVALENT_PAIRS = {
    frozenset((iso, display)): iso
    for iso, display in ISO3_TO_BWF_IOC.items()
    if iso != display
}
AMBIGUOUS_SINGLE_CODES = {
    code
    for code in ISO3_TO_BWF_IOC
    if code in {display for iso, display in ISO3_TO_BWF_IOC.items() if iso != code}
}

# Deliberate user-directed policy pairs. These remain manual overrides; they are
# never interpreted as BWF-conflict-free automatic evidence.
MANUAL_OVERRIDE_PAIRS = frozenset({("AIN", "RUS"), ("ENG", "GBR")})

CountryPairDisposition = Literal[
    "AUTO_EQUIVALENT_ELIGIBLE",
    "MANUAL_OVERRIDE_ELIGIBLE",
    "REMAIN_CONFLICTED",
]


@dataclass(frozen=True)
class CountryMismatchEvaluation:
    search_country_code: str | None
    profile_nationality_code: str | None
    canonical_search_country: str | None
    canonical_profile_country: str | None
    disposition: CountryPairDisposition
    reason_code: str
    manual_override_pair: str | None
    policy_version: str

    def as_dict(self) -> dict[str, str | None]:
        return {
            "search_country_code": self.search_country_code,
            "official_profile_bwf_nationality_code": self.profile_nationality_code,
            "canonical_search_country": self.canonical_search_country,
            "canonical_profile_country": self.canonical_profile_country,
            "disposition": self.disposition,
            "reason_code": self.reason_code,
            "manual_override_pair": self.manual_override_pair,
            "policy_version": self.policy_version,
        }


def normalize_country_code(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    normalized = value.strip().upper()
    return normalized if normalized else None


def canonical_iso3(value: object) -> str | None:
    """Resolve only an unambiguous individual code to ISO Alpha-3.

    Pair comparison is the source of truth. This helper returns ``None`` when a
    three-letter token could represent different countries in different schemes.
    """

    normalized = normalize_country_code(value)
    if normalized is None or normalized in AMBIGUOUS_SINGLE_CODES:
        return None
    if normalized in ISO3_TO_BWF_IOC:
        return normalized
    for pair, iso in DOCUMENTED_EQUIVALENT_PAIRS.items():
        if normalized in pair:
            return iso
    return None


def _documented_pair_equivalence(search_code: str | None, profile_code: str | None) -> str | None:
    if search_code is None or profile_code is None or search_code == profile_code:
        return None
    return DOCUMENTED_EQUIVALENT_PAIRS.get(frozenset((search_code, profile_code)))


def _manual_pair(search_code: str | None, profile_code: str | None) -> tuple[str, str] | None:
    if search_code is None or profile_code is None:
        return None
    direct = (search_code, profile_code)
    reverse = (profile_code, search_code)
    if direct in MANUAL_OVERRIDE_PAIRS:
        return direct
    if reverse in MANUAL_OVERRIDE_PAIRS:
        return reverse
    return None


def evaluate_country_mismatch_evidence(evidence: Mapping[str, object]) -> CountryMismatchEvaluation:
    """Classify stored country evidence without querying BWF or a database.

    The caller must separately enforce exact-name uniqueness, active-senior
    eligibility, the existing source-error boundary, and a manual approval gate.
    """

    search_code = normalize_country_code(evidence.get("search_country_code"))
    profile_code = normalize_country_code(evidence.get("official_profile_bwf_nationality_code"))
    canonical_search = canonical_iso3(search_code)
    canonical_profile = canonical_iso3(profile_code)
    override_pair = _manual_pair(search_code, profile_code)

    if override_pair is not None:
        return CountryMismatchEvaluation(
            search_country_code=search_code,
            profile_nationality_code=profile_code,
            canonical_search_country=canonical_search,
            canonical_profile_country=canonical_profile,
            disposition="MANUAL_OVERRIDE_ELIGIBLE",
            reason_code="USER_DIRECTED_SPECIAL_DESIGNATION_OVERRIDE",
            manual_override_pair=f"{override_pair[0]}:{override_pair[1]}",
            policy_version=MANUAL_OVERRIDE_POLICY_VERSION,
        )

    documented_iso = _documented_pair_equivalence(search_code, profile_code)
    if documented_iso is not None:
        return CountryMismatchEvaluation(
            search_country_code=search_code,
            profile_nationality_code=profile_code,
            canonical_search_country=documented_iso,
            canonical_profile_country=documented_iso,
            disposition="AUTO_EQUIVALENT_ELIGIBLE",
            reason_code="DOCUMENTED_ISO_BWF_IOC_EQUIVALENCE",
            manual_override_pair=None,
            policy_version=COUNTRY_MISMATCH_POLICY_VERSION,
        )

    if canonical_search is None or canonical_profile is None:
        reason_code = "COUNTRY_CODE_AMBIGUOUS_OR_UNMAPPED"
    else:
        reason_code = "CANONICAL_COUNTRY_DIFFERENT"
    return CountryMismatchEvaluation(
        search_country_code=search_code,
        profile_nationality_code=profile_code,
        canonical_search_country=canonical_search,
        canonical_profile_country=canonical_profile,
        disposition="REMAIN_CONFLICTED",
        reason_code=reason_code,
        manual_override_pair=None,
        policy_version=COUNTRY_MISMATCH_POLICY_VERSION,
    )
