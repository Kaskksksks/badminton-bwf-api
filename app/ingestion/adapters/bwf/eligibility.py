from __future__ import annotations

import re
from typing import Any, Iterable

# These markers describe a competition or event, not a person.  They are deliberately
# narrow so senior and youth/junior BWF events continue through the normal live path.
_PARA_TOURNAMENT_PATTERN = re.compile(
    r"\b(?:paralympic|para(?:[\s-]*badminton)?|wheelchair(?:[\s-]*badminton)?)\b",
    flags=re.IGNORECASE,
)
_PARA_EVENT_CODE_PATTERN = re.compile(
    r"(?<![A-Z0-9])(?:WH1|WH2|SL3|SL4|SU5|SH6)(?![A-Z0-9])",
    flags=re.IGNORECASE,
)
_PARA_EVENT_TEXT_PATTERN = re.compile(
    r"\b(?:paralympic|para(?:[\s-]*badminton)?|wheelchair(?:[\s-]*badminton)?)\b",
    flags=re.IGNORECASE,
)

_TOURNAMENT_TEXT_KEYS = (
    "name",
    "title",
    "tournament_name",
    "tournamentName",
    "tournament_type",
    "tournamentType",
    "category",
    "series",
    "description",
)
_EVENT_TEXT_KEYS = (
    "event",
    "event_type",
    "eventType",
    "event_name",
    "eventName",
    "category",
    "discipline",
)


def _strings(payload: dict[str, Any], keys: Iterable[str]) -> Iterable[str]:
    for key in keys:
        value = payload.get(key)
        if isinstance(value, str):
            yield value


def is_paralympic_tournament(payload: dict[str, Any]) -> bool:
    """Return True only when tournament metadata explicitly identifies Para badminton."""
    return any(_PARA_TOURNAMENT_PATTERN.search(value) for value in _strings(payload, _TOURNAMENT_TEXT_KEYS))


def is_paralympic_match(envelope: dict[str, Any]) -> bool:
    """Return True when a live match carries an explicit Para event classification."""
    for section_name in ("live_detail", "match_detail"):
        section = envelope.get(section_name)
        if not isinstance(section, dict):
            continue
        for value in _strings(section, _EVENT_TEXT_KEYS):
            if _PARA_EVENT_CODE_PATTERN.search(value) or _PARA_EVENT_TEXT_PATTERN.search(value):
                return True
    return False
