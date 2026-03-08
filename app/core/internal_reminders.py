from datetime import datetime, timedelta


INTERNAL_PRE_REMINDER_PREFIX = "__pre1h__::"


def build_pre_reminder_text(user_text: str) -> str:
    return f"{INTERNAL_PRE_REMINDER_PREFIX}{user_text}"


def is_internal_pre_reminder(text: str) -> bool:
    return text.startswith(INTERNAL_PRE_REMINDER_PREFIX)


def unwrap_internal_text(text: str) -> str:
    if is_internal_pre_reminder(text):
        return text[len(INTERNAL_PRE_REMINDER_PREFIX) :]
    return text


def should_create_pre_reminder(*, run_at_utc: datetime, now_local: datetime) -> bool:
    run_local_date = run_at_utc.astimezone(now_local.tzinfo).date() if now_local.tzinfo else run_at_utc.date()
    tomorrow_local = (now_local + timedelta(days=1)).date()
    return run_local_date >= tomorrow_local
