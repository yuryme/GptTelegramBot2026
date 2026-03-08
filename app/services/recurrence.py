from __future__ import annotations

from calendar import monthrange
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone


@dataclass(slots=True)
class RecurrenceRule:
    freq: str
    interval: int
    until: datetime | None


def parse_recurrence_rule(recurrence_rule: str | None, *, reference: datetime) -> RecurrenceRule | None:
    if not recurrence_rule:
        return None
    parts: dict[str, str] = {}
    for token in recurrence_rule.split(";"):
        if "=" not in token:
            continue
        key, value = token.split("=", 1)
        parts[key.strip().upper()] = value.strip()

    freq = (parts.get("FREQ") or "").upper()
    if freq not in {"HOURLY", "DAILY", "WEEKLY", "MONTHLY"}:
        return None

    try:
        interval = max(1, int(parts.get("INTERVAL", "1")))
    except ValueError:
        interval = 1

    until = _parse_until(parts.get("UNTIL"), reference=reference)
    return RecurrenceRule(freq=freq, interval=interval, until=until)


def compute_next_run_at(current_run_at: datetime, recurrence_rule: str | None) -> datetime | None:
    parsed = parse_recurrence_rule(recurrence_rule, reference=current_run_at)
    if parsed is None:
        return None

    if parsed.freq == "DAILY":
        candidate = current_run_at + timedelta(days=parsed.interval)
    elif parsed.freq == "HOURLY":
        candidate = current_run_at + timedelta(hours=parsed.interval)
    elif parsed.freq == "WEEKLY":
        candidate = current_run_at + timedelta(weeks=parsed.interval)
    else:
        candidate = _add_months(current_run_at, parsed.interval)

    if parsed.until is not None and candidate > parsed.until:
        return None
    return candidate


def _add_months(base_dt: datetime, months: int) -> datetime:
    y = base_dt.year
    m = base_dt.month + months
    y += (m - 1) // 12
    m = (m - 1) % 12 + 1
    max_day = monthrange(y, m)[1]
    d = min(base_dt.day, max_day)
    return base_dt.replace(year=y, month=m, day=d)


def _parse_until(until_raw: str | None, *, reference: datetime) -> datetime | None:
    if not until_raw:
        return None
    raw = until_raw.strip()
    if raw.endswith("Z"):
        compact = raw[:-1]
        for fmt in ("%Y%m%dT%H%M%S", "%Y%m%dT%H%M"):
            try:
                return datetime.strptime(compact, fmt).replace(tzinfo=timezone.utc)
            except ValueError:
                continue
    try:
        parsed = datetime.fromisoformat(raw)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=reference.tzinfo or timezone.utc)
    return parsed
