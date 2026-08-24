"""Small, dependency-free per-instance sliding-window rate limiter.

For a multi-instance deployment this should be replaced by a shared Redis or gateway
rate limiter.  The implementation is deliberately bounded to prevent unbounded memory
usage when clients rotate addresses.
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field
from threading import Lock
from time import monotonic


@dataclass
class SlidingWindowRateLimiter:
    limit: int
    window_seconds: float = 60.0
    max_clients: int = 10_000
    _requests: dict[str, deque[float]] = field(default_factory=dict)
    _lock: Lock = field(default_factory=Lock)

    def check(self, client_key: str) -> tuple[bool, int]:
        now = monotonic()
        cutoff = now - self.window_seconds
        with self._lock:
            history = self._requests.get(client_key)
            if history is None:
                if len(self._requests) >= self.max_clients:
                    # Evict an arbitrary inactive key; exact LRU is unnecessary for this guard.
                    self._requests.pop(next(iter(self._requests)))
                history = deque()
                self._requests[client_key] = history
            while history and history[0] <= cutoff:
                history.popleft()
            if len(history) >= self.limit:
                retry_after = max(1, int(history[0] + self.window_seconds - now) + 1)
                return False, retry_after
            history.append(now)
            return True, 0


def client_key_from_headers(x_forwarded_for: str | None, client_host: str | None) -> str:
    """Prefer the left-most proxy-provided client address, then use direct client host."""
    if x_forwarded_for:
        return x_forwarded_for.split(",", 1)[0].strip() or "unknown"
    return client_host or "unknown"
