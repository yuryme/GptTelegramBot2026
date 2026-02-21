from collections import deque
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone


class ChatRateLimiter:
    def __init__(self, max_requests: int = 5, window_seconds: int = 60) -> None:
        self._max_requests = max_requests
        self._window = timedelta(seconds=window_seconds)
        self._events: dict[int, deque[datetime]] = {}

    def allow(self, chat_id: int, now: datetime | None = None) -> bool:
        now = now or datetime.now(timezone.utc)
        queue = self._events.setdefault(chat_id, deque())
        threshold = now - self._window
        while queue and queue[0] < threshold:
            queue.popleft()
        if len(queue) >= self._max_requests:
            return False
        queue.append(now)
        return True


@dataclass
class CircuitState:
    failures: int = 0
    opened_until: datetime | None = None


class LLMCircuitBreaker:
    def __init__(self, failure_threshold: int = 3, open_seconds: int = 60) -> None:
        self._failure_threshold = failure_threshold
        self._open_seconds = open_seconds
        self._state = CircuitState()

    def is_open(self, now: datetime | None = None) -> bool:
        now = now or datetime.now(timezone.utc)
        return self._state.opened_until is not None and now < self._state.opened_until

    def register_failure(self, now: datetime | None = None) -> None:
        now = now or datetime.now(timezone.utc)
        self._state.failures += 1
        if self._state.failures >= self._failure_threshold:
            self._state.opened_until = now + timedelta(seconds=self._open_seconds)

    def register_success(self) -> None:
        self._state.failures = 0
        self._state.opened_until = None

