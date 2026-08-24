from app.core.rate_limit import SlidingWindowRateLimiter, client_key_from_headers


def test_rate_limiter_blocks_after_configured_limit() -> None:
    limiter = SlidingWindowRateLimiter(limit=2, window_seconds=60)
    assert limiter.check("198.51.100.7") == (True, 0)
    assert limiter.check("198.51.100.7") == (True, 0)
    allowed, retry_after = limiter.check("198.51.100.7")
    assert allowed is False
    assert retry_after >= 1


def test_client_key_prefers_leftmost_forwarded_address() -> None:
    assert client_key_from_headers("203.0.113.4, 10.0.0.1", "10.0.0.1") == "203.0.113.4"
    assert client_key_from_headers(None, "10.0.0.1") == "10.0.0.1"
