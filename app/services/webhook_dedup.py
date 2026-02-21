from datetime import datetime, timedelta, timezone


class WebhookDeduplicator:
    def __init__(self, ttl_seconds: int = 600) -> None:
        self._ttl = timedelta(seconds=ttl_seconds)
        self._seen: dict[int, datetime] = {}

    def mark_seen(self, update_id: int, now: datetime | None = None) -> bool:
        now = now or datetime.now(timezone.utc)
        self._cleanup(now)
        if update_id in self._seen:
            return False
        self._seen[update_id] = now
        return True

    def _cleanup(self, now: datetime) -> None:
        threshold = now - self._ttl
        stale = [uid for uid, ts in self._seen.items() if ts < threshold]
        for uid in stale:
            self._seen.pop(uid, None)

