from datetime import datetime, timezone

from app.services.cost_control import MonthlyCostGuard
from app.services.webhook_dedup import WebhookDeduplicator


def test_webhook_dedup_marks_duplicate() -> None:
    dedup = WebhookDeduplicator(ttl_seconds=60)
    now = datetime(2026, 2, 21, 12, 0, tzinfo=timezone.utc)
    assert dedup.mark_seen(1001, now=now) is True
    assert dedup.mark_seen(1001, now=now) is False


def test_webhook_dedup_expires_old_entries() -> None:
    dedup = WebhookDeduplicator(ttl_seconds=60)
    t0 = datetime(2026, 2, 21, 12, 0, tzinfo=timezone.utc)
    t1 = datetime(2026, 2, 21, 12, 2, tzinfo=timezone.utc)
    assert dedup.mark_seen(1002, now=t0) is True
    assert dedup.mark_seen(1002, now=t1) is True


def test_cost_guard_tracks_usage_and_limit() -> None:
    guard = MonthlyCostGuard(monthly_usd_limit=0.01, estimated_input_cost_per_1k=0.001, estimated_output_cost_per_1k=0.002)
    now = datetime(2026, 2, 21, 12, 0, tzinfo=timezone.utc)
    assert guard.can_spend(0.005, now=now) is True
    snapshot = guard.register_tokens(input_tokens=1000, output_tokens=1000, now=now)
    assert snapshot.total_tokens == 2000
    assert snapshot.total_usd == 0.003
    assert guard.can_spend(0.008, now=now) is False

