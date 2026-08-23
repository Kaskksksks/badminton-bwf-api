from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from app.core.config import Settings


@dataclass(frozen=True)
class PollDecision:
    mode: str
    interval_seconds: int
    next_due_at: datetime
    reason: str


def choose_poll_decision(
    settings: Settings,
    *,
    now: datetime | None = None,
    active_tournament_count: int,
    live_match_count: int,
    consecutive_failures: int = 0,
) -> PollDecision:
    """Choose a bounded polling interval; callers persist the result in source_sync_state."""
    now = now or datetime.now(timezone.utc)
    if consecutive_failures > 0:
        interval = min(settings.poll_error_backoff_max_seconds, 2 ** min(consecutive_failures, 12) * 15)
        mode, reason = "BACKOFF", "recent source failures require capped exponential backoff"
    elif live_match_count > 0:
        interval, mode, reason = settings.poll_live_match_seconds, "LIVE", "one or more verified live matches"
    elif active_tournament_count > 0:
        interval, mode, reason = settings.poll_tournament_minutes * 60, "TOURNAMENT", "active or upcoming tournament scope"
    else:
        interval, mode, reason = settings.poll_idle_minutes * 60, "IDLE", "no active tournament or live match"
    return PollDecision(mode=mode, interval_seconds=interval, next_due_at=now + timedelta(seconds=interval), reason=reason)
