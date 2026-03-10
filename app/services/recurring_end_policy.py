from __future__ import annotations

import re
from calendar import monthrange
from datetime import datetime, timedelta

from app.schemas.internal_policies import RecurrenceEndIntent


def extract_interval_from_text(text: str | None) -> int | None:
    if not text:
        return None
    lower = text.lower()
    match = re.search(r"кажды(?:й|е|ую)\s+(\d+)\s*(час|часа|часов|дн|недел|месяц)", lower)
    if not match:
        return None
    try:
        value = int(match.group(1))
    except ValueError:
        return None
    return value if value >= 1 else None


def detect_end_intent(until_expression: str | None) -> RecurrenceEndIntent | None:
    if not until_expression:
        return None
    lower = until_expression.strip().lower()
    if not lower:
        return None
    if "до конца" in lower:
        return RecurrenceEndIntent.until_period_end
    if "в течение" in lower:
        return RecurrenceEndIntent.until_duration_from_start
    if any(token in lower for token in ("следующей недели", "пока не", "на время")):
        return RecurrenceEndIntent.ambiguous
    if re.search(r"\d{1,2}:\d{2}", lower):
        return RecurrenceEndIntent.until_datetime
    if re.search(r"\d{1,2}[./]\d{1,2}([./]\d{2,4})?", lower) or re.search(r"\d{4}-\d{2}-\d{2}", lower):
        return RecurrenceEndIntent.until_date
    return RecurrenceEndIntent.until_date


def ensure_until_for_rrule(
    *,
    recurrence_rule: str,
    start_local: datetime,
) -> tuple[str, RecurrenceEndIntent]:
    parts: dict[str, str] = {}
    for token in recurrence_rule.split(";"):
        if "=" not in token:
            continue
        key, value = token.split("=", 1)
        parts[key.strip().upper()] = value.strip()
    freq = (parts.get("FREQ") or "").upper()
    if freq not in {"HOURLY", "DAILY", "WEEKLY", "MONTHLY"}:
        return recurrence_rule, RecurrenceEndIntent.until_datetime

    if parts.get("UNTIL"):
        return recurrence_rule, RecurrenceEndIntent.until_datetime

    end_hint = (parts.get("X_END_INTENT") or "").strip()
    end_expr = (parts.get("X_END_EXPR") or "").strip().lower()
    if end_hint:
        hinted = _compute_until_from_hint(start_local=start_local, end_hint=end_hint, end_expr=end_expr)
        if hinted is not None:
            parts["UNTIL"] = hinted.isoformat()
            ordered_keys = ["FREQ", "INTERVAL", "UNTIL"]
            serialized = ";".join(f"{key}={parts[key]}" for key in ordered_keys if key in parts)
            try:
                return serialized, RecurrenceEndIntent(end_hint)
            except ValueError:
                return serialized, RecurrenceEndIntent.until_datetime

    if freq == "HOURLY":
        until = start_local.replace(hour=23, minute=59, second=59, microsecond=0)
        intent = RecurrenceEndIntent.default_until_same_day
    elif freq == "DAILY":
        days_to_sunday = (6 - start_local.weekday()) % 7
        end_date = (start_local + timedelta(days=days_to_sunday)).date()
        until = start_local.replace(year=end_date.year, month=end_date.month, day=end_date.day)
        intent = RecurrenceEndIntent.default_until_end_of_week
    elif freq == "WEEKLY":
        last_day = monthrange(start_local.year, start_local.month)[1]
        until = start_local.replace(day=last_day)
        intent = RecurrenceEndIntent.default_until_end_of_month
    else:
        until = start_local.replace(month=12, day=31)
        intent = RecurrenceEndIntent.default_until_end_of_year

    if freq == "HOURLY":
        until = until.replace(tzinfo=start_local.tzinfo)
    else:
        until = until.replace(
            tzinfo=start_local.tzinfo,
            hour=start_local.hour,
            minute=start_local.minute,
            second=59,
            microsecond=0,
        )
    parts["UNTIL"] = until.isoformat()
    ordered_keys = ["FREQ", "INTERVAL", "UNTIL"]
    serialized = ";".join(f"{key}={parts[key]}" for key in ordered_keys if key in parts)
    return serialized, intent


def _compute_until_from_hint(*, start_local: datetime, end_hint: str, end_expr: str) -> datetime | None:
    if end_hint == RecurrenceEndIntent.until_period_end.value:
        if "день" in end_expr:
            return start_local.replace(hour=start_local.hour, minute=start_local.minute, second=59, microsecond=0)
        if "недел" in end_expr:
            days_to_sunday = (6 - start_local.weekday()) % 7
            end_date = (start_local + timedelta(days=days_to_sunday)).date()
            return start_local.replace(year=end_date.year, month=end_date.month, day=end_date.day, second=59, microsecond=0)
        if "год" in end_expr:
            return start_local.replace(month=12, day=31, second=59, microsecond=0)
        last_day = monthrange(start_local.year, start_local.month)[1]
        return start_local.replace(day=last_day, second=59, microsecond=0)

    if end_hint == RecurrenceEndIntent.until_duration_from_start.value:
        count_match = re.search(r"(\d+)", end_expr)
        count = int(count_match.group(1)) if count_match else 1
        if "дн" in end_expr:
            return (start_local + timedelta(days=count)).replace(second=59, microsecond=0)
        if "недел" in end_expr:
            return (start_local + timedelta(weeks=count)).replace(second=59, microsecond=0)
        if "месяц" in end_expr:
            month = start_local.month + count
            year = start_local.year + (month - 1) // 12
            month = (month - 1) % 12 + 1
            day = min(start_local.day, monthrange(year, month)[1])
            return start_local.replace(year=year, month=month, day=day, second=59, microsecond=0)
        if "год" in end_expr:
            return start_local.replace(year=start_local.year + count, second=59, microsecond=0)
    return None
