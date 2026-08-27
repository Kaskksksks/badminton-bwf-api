"""Single approved-senior competition boundary for canonical persistence and public delivery."""

from __future__ import annotations

import re
from typing import Any

from app.ingestion.adapters.bwf.eligibility import (
    is_junior_match,
    is_junior_tournament,
    is_paralympic_match,
    is_paralympic_tournament,
)

WORLD_TOUR_PATTERN = re.compile(r"\bbwf\s+(?:world\s+tour|tour\s+super\s+100)\b", re.IGNORECASE)
INDIVIDUAL_WORLDS_PATTERN = re.compile(r"\bbwf\s+world\s+championships\b", re.IGNORECASE)
CONTINENTAL_INDIVIDUAL_PATTERN = re.compile(r"\bcontinental\s+individual\s+championships\b", re.IGNORECASE)
MULTI_SPORT_PATTERN = re.compile(r"\bmulti[\s-]*sport\s+games\b", re.IGNORECASE)
NON_TARGET_PATTERN = re.compile(
    r"\b(?:international\s+(?:challenge|series)|future\s+series|continental\s+team\s+championships|world\s+team\s+championships)\b",
    re.IGNORECASE,
)


def _text(payload: dict[str, Any]) -> str:
    return " ".join(
        str(payload.get(key) or "")
        for key in ("name", "title", "tournament_name", "tournamentName", "category", "classification", "series")
    )


def classify_approved_senior_scope(
    tournament_payload: dict[str, Any], event_envelope: dict[str, Any] | None = None
) -> tuple[str, str]:
    """Classify an existing official context without inferring a competition category.

    Only BWF World Tour (including Super 100), individual World Championships,
    Continental Individual Championships, and Multi-Sport Games may enter canonical
    senior records. An absent or unfamiliar category remains excluded rather than
    being treated as senior by default.
    """

    if is_paralympic_tournament(tournament_payload) or (event_envelope and is_paralympic_match(event_envelope)):
        return "EXCLUDED_PARA", "Explicit Para tournament or event marker"
    if is_junior_tournament(tournament_payload) or (event_envelope and is_junior_match(event_envelope)):
        return "EXCLUDED_JUNIOR", "Explicit junior or U-age tournament or event marker"
    reference = _text(tournament_payload)
    if NON_TARGET_PATTERN.search(reference):
        return "EXCLUDED_NON_TARGET_SENIOR", "Explicit excluded senior competition category outside the approved World Tour, individual World Championships, Continental Individual Championships, and Multi-Sport Games scope"
    if WORLD_TOUR_PATTERN.search(reference):
        return "ELIGIBLE", "Approved BWF World Tour or Super 100 category"
    if INDIVIDUAL_WORLDS_PATTERN.search(reference) and "team" not in reference.casefold():
        return "ELIGIBLE", "Approved individual BWF World Championships category"
    if CONTINENTAL_INDIVIDUAL_PATTERN.search(reference):
        return "ELIGIBLE", "Approved Continental Individual Championships category"
    if MULTI_SPORT_PATTERN.search(reference):
        return "ELIGIBLE", "Approved Multi-Sport Games category"
    return "EXCLUDED_NON_TARGET_SENIOR", "Outside the approved World Tour, individual World Championships, Continental Individual Championships, and Multi-Sport Games scope"
