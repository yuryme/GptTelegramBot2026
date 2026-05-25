from __future__ import annotations

from calendar import monthrange
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone


@dataclass(slots=True)
class RecurrenceRule:
    freq: str
    interval: int
    until: datetime | None
    byday: tuple[int, ...] = ()
    bymonthday: int | None = None


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
    if freq not in {"MINUTELY", "HOURLY", "DAILY", "WEEKLY", "MONTHLY"}:
        return None

    try:
        interval = max(1, int(parts.get("INTERVAL", "1")))
    except ValueError:
        interval = 1

    until = _parse_until(parts.get("UNTIL"), reference=reference)
    byday = _parse_byday(parts.get("BYDAY"))
    bymonthday = _parse_bymonthday(parts.get("BYMONTHDAY"))
    return RecurrenceRule(freq=freq, interval=interval, until=until, byday=byday, bymonthday=bymonthday)


def compute_next_run_at(current_run_at: datetime, recurrence_rule: str | None) -> datetime | None:
    parsed = parse_recurrence_rule(recurrence_rule, reference=current_run_at)
    if parsed is None:
        return None

    if parsed.freq == "MINUTELY":
        candidate = current_run_at + timedelta(minutes=parsed.interval)
    elif parsed.freq == "DAILY":
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


def expand_occurrences(start_run_at: datetime, recurrence_rule: str | None) -> list[datetime]:
    parsed = parse_recurrence_rule(recurrence_rule, reference=start_run_at)
    if parsed is None:
        return [start_run_at]

    if parsed.until is None:
        return [start_run_at]

    if parsed.freq == "MINUTELY":
        return _expand_minutely(start_run_at, parsed)
    if parsed.freq == "HOURLY":
        return _expand_hourly(start_run_at, parsed)
    if parsed.freq == "DAILY":
        return _expand_daily(start_run_at, parsed)
    if parsed.freq == "WEEKLY":
        return _expand_weekly(start_run_at, parsed)
    return _expand_monthly(start_run_at, parsed)


def _expand_minutely(start_run_at: datetime, parsed: RecurrenceRule) -> list[datetime]:
    current = start_run_at
    items: list[datetime] = []
    while current <= (parsed.until or start_run_at):
        items.append(current)
        current = current + timedelta(minutes=parsed.interval)
    return items


def _expand_hourly(start_run_at: datetime, parsed: RecurrenceRule) -> list[datetime]:
    current = start_run_at
    items: list[datetime] = []
    while current <= (parsed.until or start_run_at):
        items.append(current)
        current = current + timedelta(hours=parsed.interval)
    return items


def _expand_daily(start_run_at: datetime, parsed: RecurrenceRule) -> list[datetime]:
    current = start_run_at
    items: list[datetime] = []
    while current <= (parsed.until or start_run_at):
        items.append(current)
        current = current + timedelta(days=parsed.interval)
    return items


def _expand_weekly(start_run_at: datetime, parsed: RecurrenceRule) -> list[datetime]:
    until = parsed.until or start_run_at
    weekdays = parsed.byday or (start_run_at.weekday(),)
    anchor_week_start = start_run_at.date() - timedelta(days=start_run_at.weekday())
    current_date = start_run_at.date()
    items: list[datetime] = []
    seen: set[datetime] = set()

    while current_date <= until.date():
        candidate = start_run_at.replace(
            year=current_date.year,
            month=current_date.month,
            day=current_date.day,
        )
        week_start = current_date - timedelta(days=current_date.weekday())
        weeks_since_anchor = (week_start - anchor_week_start).days // 7
        if (
            current_date.weekday() in weekdays
            and weeks_since_anchor % parsed.interval == 0
            and candidate >= start_run_at
            and candidate <= until
            and candidate not in seen
        ):
            items.append(candidate)
            seen.add(candidate)
        current_date = current_date + timedelta(days=1)
    return items


def _expand_monthly(start_run_at: datetime, parsed: RecurrenceRule) -> list[datetime]:
    until = parsed.until or start_run_at
    current = start_run_at
    target_day = parsed.bymonthday or start_run_at.day
    items: list[datetime] = []
    while current <= until:
        max_day = monthrange(current.year, current.month)[1]
        day = min(target_day, max_day)
        candidate = current.replace(day=day)
        if candidate >= start_run_at and candidate <= until:
            items.append(candidate)
        current = _add_months(current, parsed.interval)
    return items


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


def _parse_byday(raw: str | None) -> tuple[int, ...]:
    if not raw:
        return ()
    mapping = {
        "MO": 0,
        "TU": 1,
        "WE": 2,
        "TH": 3,
        "FR": 4,
        "SA": 5,
        "SU": 6,
    }
    values: list[int] = []
    for token in raw.split(","):
        day = mapping.get(token.strip().upper())
        if day is not None and day not in values:
            values.append(day)
    return tuple(values)


def _parse_bymonthday(raw: str | None) -> int | None:
    if not raw:
        return None
    try:
        value = int(raw.strip())
    except ValueError:
        return None
    return value if 1 <= value <= 31 else None
