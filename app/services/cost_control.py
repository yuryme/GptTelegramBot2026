from dataclasses import dataclass
from datetime import datetime, timezone


@dataclass
class UsageSnapshot:
    month_key: str
    total_tokens: int
    total_usd: float


class MonthlyCostGuard:
    def __init__(
        self,
        monthly_usd_limit: float = 10.0,
        estimated_input_cost_per_1k: float = 0.0003,
        estimated_output_cost_per_1k: float = 0.0012,
    ) -> None:
        self.monthly_usd_limit = monthly_usd_limit
        self.estimated_input_cost_per_1k = estimated_input_cost_per_1k
        self.estimated_output_cost_per_1k = estimated_output_cost_per_1k
        self._usage: dict[str, UsageSnapshot] = {}
        self._alerted_thresholds: dict[str, set[int]] = {}

    def _month_key(self, now: datetime | None = None) -> str:
        now = now or datetime.now(timezone.utc)
        return f"{now.year:04d}-{now.month:02d}"

    def can_spend(self, estimated_usd: float, now: datetime | None = None) -> bool:
        key = self._month_key(now)
        snapshot = self._usage.get(key, UsageSnapshot(key, 0, 0.0))
        return snapshot.total_usd + estimated_usd <= self.monthly_usd_limit

    def register_tokens(
        self,
        input_tokens: int,
        output_tokens: int,
        now: datetime | None = None,
    ) -> UsageSnapshot:
        key = self._month_key(now)
        snapshot = self._usage.get(key, UsageSnapshot(key, 0, 0.0))
        usd = (input_tokens / 1000.0) * self.estimated_input_cost_per_1k
        usd += (output_tokens / 1000.0) * self.estimated_output_cost_per_1k
        snapshot.total_tokens += input_tokens + output_tokens
        snapshot.total_usd += usd
        self._usage[key] = snapshot
        return snapshot

    def get_new_alert_thresholds(self, now: datetime | None = None) -> list[int]:
        key = self._month_key(now)
        snapshot = self._usage.get(key, UsageSnapshot(key, 0, 0.0))
        used_pct = (snapshot.total_usd / self.monthly_usd_limit * 100.0) if self.monthly_usd_limit > 0 else 100.0
        thresholds = [50, 80, 100]
        alerted = self._alerted_thresholds.setdefault(key, set())
        newly_crossed = [t for t in thresholds if used_pct >= t and t not in alerted]
        alerted.update(newly_crossed)
        return newly_crossed
