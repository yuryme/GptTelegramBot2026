from datetime import datetime, timedelta, timezone

from app.services.guardrails import ChatRateLimiter, LLMCircuitBreaker


def test_chat_rate_limiter_blocks_after_limit() -> None:
    limiter = ChatRateLimiter(max_requests=2, window_seconds=60)
    now = datetime(2026, 2, 22, 0, 0, tzinfo=timezone.utc)
    assert limiter.allow(1, now=now) is True
    assert limiter.allow(1, now=now + timedelta(seconds=1)) is True
    assert limiter.allow(1, now=now + timedelta(seconds=2)) is False


def test_chat_rate_limiter_resets_after_window() -> None:
    limiter = ChatRateLimiter(max_requests=1, window_seconds=10)
    now = datetime(2026, 2, 22, 0, 0, tzinfo=timezone.utc)
    assert limiter.allow(1, now=now) is True
    assert limiter.allow(1, now=now + timedelta(seconds=11)) is True


def test_llm_circuit_breaker_opens_and_closes() -> None:
    breaker = LLMCircuitBreaker(failure_threshold=2, open_seconds=30)
    now = datetime(2026, 2, 22, 0, 0, tzinfo=timezone.utc)
    assert breaker.is_open(now=now) is False
    breaker.register_failure(now=now)
    assert breaker.is_open(now=now) is False
    breaker.register_failure(now=now)
    assert breaker.is_open(now=now + timedelta(seconds=1)) is True
    assert breaker.is_open(now=now + timedelta(seconds=31)) is False

