from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, datetime
from zoneinfo import ZoneInfo

from app.schemas.commands import AssistantCommand, CommandName, DayReference, ReminderInput

_TIME_PATTERN = re.compile(r"\b([01]?\d|2[0-3])[:.\-]([0-5]\d)\b")
_HOUR_ONLY_PATTERN = re.compile(r"\b([01]?\d|2[0-3])\b")
_ISO_DATE_PATTERN = re.compile(r"\b(\d{4})-(\d{2})-(\d{2})\b")

_RU_MONTHS = {
    "\u044f\u043d\u0432\u0430\u0440\u044f": 1,
    "\u0444\u0435\u0432\u0440\u0430\u043b\u044f": 2,
    "\u043c\u0430\u0440\u0442\u0430": 3,
    "\u0430\u043f\u0440\u0435\u043b\u044f": 4,
    "\u043c\u0430\u044f": 5,
    "\u0438\u044e\u043d\u044f": 6,
    "\u0438\u044e\u043b\u044f": 7,
    "\u0430\u0432\u0433\u0443\u0441\u0442\u0430": 8,
    "\u0441\u0435\u043d\u0442\u044f\u0431\u0440\u044f": 9,
    "\u043e\u043a\u0442\u044f\u0431\u0440\u044f": 10,
    "\u043d\u043e\u044f\u0431\u0440\u044f": 11,
    "\u0434\u0435\u043a\u0430\u0431\u0440\u044f": 12,
}

_RU_WEEKDAYS = {
    "\u043f\u043e\u043d\u0435\u0434\u0435\u043b\u044c\u043d\u0438\u043a": 0,
    "\u0432\u0442\u043e\u0440\u043d\u0438\u043a": 1,
    "\u0441\u0440\u0435\u0434\u0443": 2,
    "\u0441\u0440\u0435\u0434\u0430": 2,
    "\u0447\u0435\u0442\u0432\u0435\u0440\u0433": 3,
    "\u043f\u044f\u0442\u043d\u0438\u0446\u0443": 4,
    "\u043f\u044f\u0442\u043d\u0438\u0446\u0430": 4,
    "\u0441\u0443\u0431\u0431\u043e\u0442\u0443": 5,
    "\u0441\u0443\u0431\u0431\u043e\u0442\u0430": 5,
    "\u0432\u043e\u0441\u043a\u0440\u0435\u0441\u0435\u043d\u044c\u0435": 6,
}


@dataclass(slots=True)
class TemporalNormalizer:
    timezone: str

    def normalize_command(
        self,
        *,
        command: AssistantCommand,
        user_text: str,
        now: datetime,
    ) -> AssistantCommand:
        if command.command != CommandName.create:
            return command

        normalized_items: list[ReminderInput] = []
        for item in command.reminders:
            normalized_items.append(self._normalize_reminder(item=item, user_text=user_text, now=now))
        return command.model_copy(update={"reminders": normalized_items})

    def _normalize_reminder(self, *, item: ReminderInput, user_text: str, now: datetime) -> ReminderInput:
        text = user_text.lower()
        inferred_day_reference = _infer_day_reference(text)
        inferred_weekday = _infer_weekday(text)
        inferred_date = _infer_date_value(text, now.date())
        inferred_time = _infer_time_text(text)

        update: dict[str, object] = {}
        day_reference = item.day_reference

        if day_reference is None and inferred_day_reference is not None and item.run_at is not None:
            update["day_reference"] = inferred_day_reference
            update["run_at"] = None
            day_reference = inferred_day_reference

        if day_reference is None and inferred_day_reference is not None and item.run_at is None:
            update["day_reference"] = inferred_day_reference
            day_reference = inferred_day_reference

        if day_reference == DayReference.weekday and item.weekday is None and inferred_weekday is not None:
            update["weekday"] = inferred_weekday

        if day_reference == DayReference.specific_date and item.date_value is None:
            if inferred_date is not None:
                update["date_value"] = inferred_date
            elif item.run_at is not None:
                run_local = item.run_at.astimezone(ZoneInfo(self.timezone))
                update["date_value"] = run_local.date()

        if item.explicit_time_provided:
            if item.time_value:
                parsed = _normalize_time_text(item.time_value)
                if parsed is not None:
                    update["time_value"] = parsed
            elif inferred_time is not None:
                update["time_value"] = inferred_time
        elif inferred_time is not None:
            update["time_value"] = inferred_time
            update["explicit_time_provided"] = True

        if not update:
            return item
        return item.model_copy(update=update)


def _infer_day_reference(text: str) -> DayReference | None:
    if "\u043f\u043e\u0441\u043b\u0435\u0437\u0430\u0432\u0442\u0440\u0430" in text:
        return DayReference.day_after_tomorrow
    if "\u0437\u0430\u0432\u0442\u0440\u0430" in text:
        return DayReference.tomorrow
    if "\u0441\u0435\u0433\u043e\u0434\u043d\u044f" in text:
        return DayReference.today
    if _infer_weekday(text) is not None:
        return DayReference.weekday
    if _ISO_DATE_PATTERN.search(text) or _infer_russian_date(text) is not None:
        return DayReference.specific_date
    return None


def _infer_weekday(text: str) -> int | None:
    for token, value in _RU_WEEKDAYS.items():
        if token in text:
            return value
    return None


def _infer_date_value(text: str, base_date: date) -> date | None:
    iso = _ISO_DATE_PATTERN.search(text)
    if iso:
        try:
            return date(int(iso.group(1)), int(iso.group(2)), int(iso.group(3)))
        except ValueError:
            return None
    rus = _infer_russian_date(text)
    if rus is None:
        return None
    day, month = rus
    year = base_date.year
    try:
        candidate = date(year, month, day)
    except ValueError:
        return None
    if candidate < base_date:
        try:
            return date(year + 1, month, day)
        except ValueError:
            return candidate
    return candidate


def _infer_russian_date(text: str) -> tuple[int, int] | None:
    for month_name, month_idx in _RU_MONTHS.items():
        m = re.search(rf"\b([0-3]?\d)\s+{month_name}\b", text)
        if m:
            return int(m.group(1)), month_idx
    return None


def _infer_time_text(text: str) -> str | None:
    precise = _TIME_PATTERN.search(text)
    if precise:
        return f"{int(precise.group(1)):02d}:{int(precise.group(2)):02d}"

    if "\u0020\u0432\u0020" in text:
        after_v = text.split("\u0020\u0432\u0020", 1)[1]
        hour = _HOUR_ONLY_PATTERN.match(after_v.strip())
        if hour:
            return f"{int(hour.group(1)):02d}:00"
    return None


def _normalize_time_text(value: str) -> str | None:
    m = _TIME_PATTERN.match(value.strip())
    if not m:
        return None
    return f"{int(m.group(1)):02d}:{int(m.group(2)):02d}"
