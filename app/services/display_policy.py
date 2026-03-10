from __future__ import annotations

from datetime import datetime, timedelta

from app.core.internal_reminders import should_create_pre_reminder
from app.schemas.internal_policies import InternalDisplayPolicy, PreReminderMode


def should_schedule_pre_reminder(
    *,
    run_at_utc: datetime,
    now_local: datetime,
    policy: InternalDisplayPolicy | None = None,
) -> bool:
    if policy is None or policy.pre_reminder_mode == PreReminderMode.auto:
        return should_create_pre_reminder(run_at_utc=run_at_utc, now_local=now_local)
    if policy.pre_reminder_mode == PreReminderMode.disabled:
        return False
    return policy.pre_reminder_mode == PreReminderMode.minutes_before and (policy.pre_reminder_minutes or 0) > 0


def pre_reminder_delta(policy: InternalDisplayPolicy | None = None) -> timedelta:
    if policy is None or policy.pre_reminder_mode == PreReminderMode.auto:
        return timedelta(hours=1)
    if policy.pre_reminder_mode == PreReminderMode.minutes_before and policy.pre_reminder_minutes:
        return timedelta(minutes=policy.pre_reminder_minutes)
    return timedelta(hours=1)

