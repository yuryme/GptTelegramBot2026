from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta

from pydantic import ValidationError

from app.schemas.commands import AssistantCommand, assistant_command_adapter
from app.schemas.internal_policies import (
    CompiledCreateReminderPlan,
    InternalDisplayPolicy,
    InternalRecurrencePolicy,
    PreReminderMode,
    RecurrenceEndIntent,
    RecurrenceEndKind,
    RecurrenceKind,
)
from app.schemas.semantic_draft import CreateReminderDraft, ScheduleDraft, SemanticCommandDraft
from app.services.recurring_end_policy import detect_end_intent, extract_interval_from_text


class SemanticDraftCompilationError(ValueError):
    pass


@dataclass(slots=True)
class PeriodWindow:
    start_date: date
    start_time: str
    until: datetime


class SemanticDraftCompiler:
    def compile_to_command(self, *, draft: SemanticCommandDraft, now: datetime | None = None) -> AssistantCommand:
        if draft.intent == "create_reminders":
            if not draft.create_items:
                raise SemanticDraftCompilationError("create draft must contain at least one create item")
            reminders = [plan.reminder_payload for plan in self.compile_create_plans(draft=draft, now=now)]
            try:
                return assistant_command_adapter.validate_python({"command": "create_reminders", "reminders": reminders})
            except ValidationError as exc:
                raise SemanticDraftCompilationError("compiled create command does not match final command schema") from exc

        if draft.passthrough_command is None:
            raise SemanticDraftCompilationError("passthrough_command is required for non-create intents")
        payload = self._normalize_passthrough_command(draft.passthrough_command)
        try:
            return assistant_command_adapter.validate_python(payload)
        except ValidationError as exc:
            raise SemanticDraftCompilationError("passthrough_command does not match final command schema") from exc

    def _normalize_passthrough_command(self, payload: dict) -> dict:
        normalized = dict(payload)
        if "command" not in normalized:
            action = str(normalized.pop("action", "")).strip().lower()
            if action == "list":
                normalized["command"] = "list_reminders"
            elif action == "delete":
                normalized["command"] = "delete_reminders"

        if normalized.get("command") == "list_reminders":
            status = normalized.get("status")
            if normalized.get("mode") is None:
                normalized["mode"] = "status" if status in {"pending", "done", "deleted"} else "all"
            if status == "all":
                normalized.pop("status", None)
        return normalized

    def compile_create_plans(
        self,
        *,
        draft: SemanticCommandDraft,
        now: datetime | None = None,
    ) -> list[CompiledCreateReminderPlan]:
        if draft.intent != "create_reminders":
            return []
        current = now or datetime.now()
        return [self._compile_create_item(item, now=current) for item in draft.create_items]

    def _compile_create_item(self, item: CreateReminderDraft, *, now: datetime) -> CompiledCreateReminderPlan:
        cleaned_text = self._cleanup_wrapper_markers(
            reminder_text=item.reminder_text,
            raw_context=item.raw_context,
            day_expression=item.day_expression,
            time_expression=item.time_expression,
            date_expression=item.date_expression,
            recurrence_expression=item.recurrence_expression,
        )
        if item.schedule is not None:
            return self._compile_scheduled_item(item=item, cleaned_text=cleaned_text)

        result: dict[str, object] = {
            "text": cleaned_text,
            "explicit_time_provided": False,
        }

        day_expr = (item.day_expression or "").strip().lower()
        date_expr = (item.date_expression or "").strip()
        time_expr = (item.time_expression or "").strip()
        period = self._detect_period_window(item=item, base_date=now.date()) if self._looks_like_recurrence(item) else None

        day_reference: str | None = None
        if period is not None:
            day_reference = "specific_date"
            result["date_value"] = period.start_date
            result["time"] = period.start_time
            result["explicit_time_provided"] = True
        elif day_expr:
            if "послезавтра" in day_expr:
                day_reference = "day_after_tomorrow"
            elif "завтра" in day_expr:
                day_reference = "tomorrow"
            elif "сегодня" in day_expr:
                day_reference = "today"
            elif self._weekday_to_num(day_expr) is not None:
                day_reference = "weekday"
                result["weekday"] = self._weekday_to_num(day_expr)

        if date_expr and period is None:
            day_reference = "specific_date"
            result["date_value"] = self._normalize_date(date_expr, base_date=now.date()) or date_expr

        if day_reference is not None:
            result["day_reference"] = day_reference
        else:
            result["day_reference"] = "today"

        normalized_time = self._normalize_time(time_expr)
        if normalized_time is not None and period is None:
            result["time"] = normalized_time
            result["explicit_time_provided"] = True

        recurrence = self._compile_recurrence_policy(item, period_until=period.until if period else None)
        if recurrence.legacy_rule:
            result["recurrence_rule"] = recurrence.legacy_rule

        display = self._compile_display_policy(item=item, user_time=normalized_time)
        return CompiledCreateReminderPlan(reminder_payload=result, recurrence=recurrence, display=display)

    def _compile_scheduled_item(self, *, item: CreateReminderDraft, cleaned_text: str) -> CompiledCreateReminderPlan:
        schedule = item.schedule
        assert schedule is not None

        result: dict[str, object] = {
            "text": cleaned_text,
            "run_at": schedule.start_at,
            "explicit_time_provided": True,
        }
        recurrence = self._compile_schedule_recurrence(schedule)
        if recurrence.legacy_rule:
            result["recurrence_rule"] = recurrence.legacy_rule
        display = self._compile_display_policy(
            item=item,
            user_time=schedule.start_at.strftime("%H:%M"),
        )
        return CompiledCreateReminderPlan(reminder_payload=result, recurrence=recurrence, display=display)

    def _compile_schedule_recurrence(self, schedule: ScheduleDraft) -> InternalRecurrencePolicy:
        if schedule.kind == "once":
            return InternalRecurrencePolicy(
                kind=RecurrenceKind.one_time,
                interval=1,
                end_kind=RecurrenceEndKind.never,
                end_intent=None,
                legacy_rule=None,
            )

        frequency_to_kind = {
            "minutely": RecurrenceKind.minutely,
            "hourly": RecurrenceKind.hourly,
            "daily": RecurrenceKind.daily,
            "weekly": RecurrenceKind.weekly,
            "monthly": RecurrenceKind.monthly,
        }
        if schedule.frequency is None:
            raise SemanticDraftCompilationError("recurring schedule must include frequency")
        kind = frequency_to_kind[schedule.frequency]
        interval = schedule.interval or 1
        weekdays = schedule.weekdays or []
        month_day = schedule.month_day
        legacy_rule = self._build_legacy_rule(
            kind=kind,
            interval=interval,
            until=schedule.end_at,
            end_intent=RecurrenceEndIntent.until_datetime if schedule.end_at else None,
            end_expression=None,
            weekdays=weekdays,
            month_day=month_day,
        )
        return InternalRecurrencePolicy(
            kind=kind,
            interval=interval,
            weekdays=weekdays,
            month_day=month_day,
            end_kind=RecurrenceEndKind.until_datetime if schedule.end_at else RecurrenceEndKind.never,
            end_intent=RecurrenceEndIntent.until_datetime if schedule.end_at else None,
            until=schedule.end_at,
            legacy_rule=legacy_rule,
        )

    def _compile_recurrence_policy(
        self,
        item: CreateReminderDraft,
        *,
        period_until: datetime | None = None,
    ) -> InternalRecurrencePolicy:
        raw_source = item.recurrence_expression or item.raw_context or item.reminder_text
        raw = (raw_source or "").strip().lower()
        interval = item.recurrence_interval or extract_interval_from_text(raw_source) or 1
        weekdays: list[int] = []
        month_day: int | None = None
        kind = RecurrenceKind.one_time
        legacy_rule: str | None = None

        if raw:
            if raw.startswith("freq="):
                legacy_rule = raw_source.strip()
                return self._build_policy_from_rrule(legacy_rule)

            if any(token in raw for token in ("минут", "minute")) and "кажд" in raw:
                kind = RecurrenceKind.minutely
            elif any(token in raw for token in ("каждый день", "ежеднев", "every day")):
                kind = RecurrenceKind.daily
            elif (
                any(token in raw for token in ("каждый час", "ежечас", "every hour"))
                or ("кажд" in raw and "час" in raw)
            ):
                kind = RecurrenceKind.hourly
            elif any(token in raw for token in ("будни", "по будням", "weekday")):
                kind = RecurrenceKind.weekly
                weekdays = [0, 1, 2, 3, 4]
            elif (
                any(token in raw for token in ("каждую неделю", "еженед", "weekly", "каждый вторник", "каждую среду"))
                or ("кажд" in raw and "недел" in raw)
            ):
                kind = RecurrenceKind.weekly
                weekdays = self._extract_weekdays(raw)
            elif (
                any(token in raw for token in ("каждый месяц", "ежемесяч", "monthly"))
                or ("кажд" in raw and "месяц" in raw)
            ):
                kind = RecurrenceKind.monthly
                month_day = self._extract_month_day(raw)

        if kind == RecurrenceKind.one_time:
            return InternalRecurrencePolicy(
                kind=kind,
                interval=1,
                end_kind=RecurrenceEndKind.never,
                end_intent=None,
                legacy_rule=None,
            )

        until_dt = period_until or self._parse_recurrence_until(item.recurrence_until_expression)
        end_intent = detect_end_intent(item.recurrence_until_expression)
        if end_intent == RecurrenceEndIntent.ambiguous:
            raise SemanticDraftCompilationError("ambiguous recurrence end expression")
        if until_dt is None and end_intent in (RecurrenceEndIntent.until_date, RecurrenceEndIntent.until_datetime):
            raise SemanticDraftCompilationError("unsupported recurrence end expression")
        end_kind = RecurrenceEndKind.until_datetime if until_dt is not None else RecurrenceEndKind.never
        legacy_rule = self._build_legacy_rule(
            kind=kind,
            interval=interval,
            until=until_dt,
            end_intent=end_intent,
            end_expression=item.recurrence_until_expression,
            weekdays=weekdays,
            month_day=month_day,
        )

        return InternalRecurrencePolicy(
            kind=kind,
            interval=interval,
            weekdays=weekdays,
            month_day=month_day,
            end_kind=end_kind,
            end_intent=end_intent,
            until=until_dt,
            legacy_rule=legacy_rule,
        )

    def _compile_display_policy(self, *, item: CreateReminderDraft, user_time: str | None) -> InternalDisplayPolicy:
        raw = (item.pre_reminder_expression or "").strip().lower()
        if raw and any(token in raw for token in ("без", "no", "disable")):
            return InternalDisplayPolicy(
                user_time=user_time,
                pre_reminder_mode=PreReminderMode.disabled,
                pre_reminder_minutes=None,
            )

        minutes = None
        if raw:
            m = re.search(r"(\d{1,3})\s*(мин|minute)", raw)
            if m:
                minutes = int(m.group(1))
            elif "час" in raw or "hour" in raw:
                minutes = 60

        if minutes is not None:
            return InternalDisplayPolicy(
                user_time=user_time,
                pre_reminder_mode=PreReminderMode.minutes_before,
                pre_reminder_minutes=minutes,
            )

        return InternalDisplayPolicy(user_time=user_time, pre_reminder_mode=PreReminderMode.auto)

    def _build_policy_from_rrule(self, rrule: str) -> InternalRecurrencePolicy:
        parts: dict[str, str] = {}
        for token in rrule.split(";"):
            if "=" not in token:
                continue
            key, value = token.split("=", 1)
            parts[key.strip().upper()] = value.strip()

        freq = parts.get("FREQ", "").upper()
        interval = max(1, int(parts.get("INTERVAL", "1") or "1"))
        until = self._parse_recurrence_until(parts.get("UNTIL"))
        weekdays = []
        byday_raw = parts.get("BYDAY", "")
        byday_mapping = {"MO": 0, "TU": 1, "WE": 2, "TH": 3, "FR": 4, "SA": 5, "SU": 6}
        for token in byday_raw.split(","):
            day = byday_mapping.get(token.strip().upper())
            if day is not None:
                weekdays.append(day)
        month_day = None
        try:
            if parts.get("BYMONTHDAY"):
                month_day = int(parts["BYMONTHDAY"])
        except ValueError:
            month_day = None

        kind = RecurrenceKind.one_time
        if freq == "MINUTELY":
            kind = RecurrenceKind.minutely
        elif freq == "DAILY":
            kind = RecurrenceKind.daily
        elif freq == "HOURLY":
            kind = RecurrenceKind.hourly
        elif freq == "WEEKLY":
            kind = RecurrenceKind.weekly
        elif freq == "MONTHLY":
            kind = RecurrenceKind.monthly

        return InternalRecurrencePolicy(
            kind=kind,
            interval=interval,
            weekdays=weekdays,
            month_day=month_day,
            end_kind=RecurrenceEndKind.until_datetime if until else RecurrenceEndKind.never,
            end_intent=RecurrenceEndIntent.until_datetime if until else None,
            until=until,
            legacy_rule=rrule,
        )

    def _build_legacy_rule(
        self,
        *,
        kind: RecurrenceKind,
        interval: int,
        until: datetime | None,
        end_intent: RecurrenceEndIntent | None,
        end_expression: str | None,
        weekdays: list[int],
        month_day: int | None,
    ) -> str:
        freq = {
            RecurrenceKind.minutely: "MINUTELY",
            RecurrenceKind.hourly: "HOURLY",
            RecurrenceKind.daily: "DAILY",
            RecurrenceKind.weekly: "WEEKLY",
            RecurrenceKind.monthly: "MONTHLY",
        }.get(kind)
        if freq is None:
            raise SemanticDraftCompilationError("one_time reminders do not have recurrence_rule")

        tokens = [f"FREQ={freq}"]
        if interval > 1:
            tokens.append(f"INTERVAL={interval}")
        if kind == RecurrenceKind.weekly and weekdays:
            tokens.append(f"BYDAY={self._encode_byday(weekdays)}")
        if kind == RecurrenceKind.monthly and month_day is not None:
            tokens.append(f"BYMONTHDAY={month_day}")
        if until is not None:
            tokens.append(f"UNTIL={until.isoformat()}")
        elif end_intent in (RecurrenceEndIntent.until_period_end, RecurrenceEndIntent.until_duration_from_start):
            tokens.append(f"X_END_INTENT={end_intent.value}")
            if end_expression:
                encoded = end_expression.strip().replace(";", ",")
                tokens.append(f"X_END_EXPR={encoded}")
        return ";".join(tokens)

    def _parse_recurrence_until(self, raw_value: str | None) -> datetime | None:
        if not raw_value:
            return None
        raw = raw_value.strip()
        if not raw:
            return None
        m = re.fullmatch(r"(\d{4})-(\d{2})-(\d{2})", raw)
        if m:
            y, mon, d = int(m.group(1)), int(m.group(2)), int(m.group(3))
            return datetime.combine(date(y, mon, d), time(23, 59, 59))
        try:
            return datetime.fromisoformat(raw)
        except ValueError:
            pass

        return None

    def _encode_byday(self, weekdays: list[int]) -> str:
        mapping = {
            0: "MO",
            1: "TU",
            2: "WE",
            3: "TH",
            4: "FR",
            5: "SA",
            6: "SU",
        }
        return ",".join(mapping[day] for day in weekdays if day in mapping)

    def _extract_weekdays(self, text: str) -> list[int]:
        values: list[int] = []
        mapping = {
            "понедельник": 0,
            "вторник": 1,
            "сред": 2,
            "четверг": 3,
            "пятниц": 4,
            "суббот": 5,
            "воскрес": 6,
        }
        for token, day in mapping.items():
            if token in text and day not in values:
                values.append(day)
        return values

    def _extract_month_day(self, text: str) -> int | None:
        m = re.search(r"\b([1-9]|[12]\d|3[01])\b", text)
        if not m:
            return None
        day = int(m.group(1))
        return day if 1 <= day <= 31 else None

    def _cleanup_wrapper_markers(
        self,
        *,
        reminder_text: str,
        raw_context: str | None,
        day_expression: str | None,
        time_expression: str | None,
        date_expression: str | None,
        recurrence_expression: str | None,
    ) -> str:
        text = reminder_text.strip()
        if not text:
            return text

        context = (raw_context or "").strip().lower()
        has_temporal_or_schedule_markers = any(
            (
                bool((day_expression or "").strip()),
                bool((time_expression or "").strip()),
                bool((date_expression or "").strip()),
                bool((recurrence_expression or "").strip()),
            )
        )
        has_raw_context = bool(context)
        looks_like_command_wrapper = "напомни" in context or (
            not has_raw_context
            and has_temporal_or_schedule_markers
            and text.lower().startswith(("что ", "чтобы ", "напомни", "напомни:"))
        )
        if not looks_like_command_wrapper:
            return text

        patterns = [
            re.compile(r"^\s*напомни\s*[:,]?\s+", flags=re.IGNORECASE),
            re.compile(r"^\s*что\s+", flags=re.IGNORECASE),
            re.compile(r"^\s*чтобы\s+", flags=re.IGNORECASE),
        ]
        normalized = text
        changed = True
        while changed:
            changed = False
            for pattern in patterns:
                updated = pattern.sub("", normalized, count=1).strip()
                if updated != normalized:
                    normalized = updated
                    changed = True
        return normalized or text

    def _looks_like_recurrence(self, item: CreateReminderDraft) -> bool:
        raw = " ".join(
            value.strip().lower()
            for value in (
                item.recurrence_expression,
                item.recurrence_until_expression,
                item.raw_context,
            )
            if value and value.strip()
        )
        return raw.startswith("freq=") or "кажд" in raw or "ежеднев" in raw or "every" in raw

    def _detect_period_window(self, *, item: CreateReminderDraft, base_date: date) -> PeriodWindow | None:
        raw = " ".join(
            value.strip().lower()
            for value in (
                item.period_start_expression,
                item.period_end_expression,
                item.recurrence_until_expression,
                item.raw_context,
                item.day_expression,
                item.date_expression,
            )
            if value and value.strip()
        )
        if not raw:
            return None

        period_date = self._period_date_from_text(raw, base_date=base_date)
        explicit_range = self._extract_period_time_range(raw)
        if explicit_range is not None:
            start_time, end_time = explicit_range
            return PeriodWindow(
                start_date=period_date,
                start_time=start_time.strftime("%H:%M"),
                until=datetime.combine(period_date, end_time),
            )

        is_whole_day = (
            "в течение" in raw and "дн" in raw
        ) or "весь день" in raw or "завтрашнего дня" in raw or "сегодняшнего дня" in raw
        if not is_whole_day:
            return None

        return PeriodWindow(
            start_date=period_date,
            start_time="00:00",
            until=datetime.combine(period_date, time(23, 59, 59)),
        )

    def _period_date_from_text(self, text: str, *, base_date: date) -> date:
        if "послезавтра" in text:
            return base_date + timedelta(days=2)
        if "завтра" in text or "завтраш" in text:
            return base_date + timedelta(days=1)
        if "сегодня" in text or "сегодняш" in text:
            return base_date

        parsed_date = self._normalize_date(text, base_date=base_date)
        return parsed_date or base_date

    def _extract_period_time_range(self, text: str) -> tuple[time, time] | None:
        match = re.search(
            r"\bс\s+([01]?\d|2[0-3])(?:[:.\-]([0-5]\d))?(?:\s*час(?:а|ов)?)?\s+до\s+([01]?\d|2[0-3])(?:[:.\-]([0-5]\d))?(?:\s*час(?:а|ов)?)?\b",
            text,
        )
        if not match:
            return None
        start = time(int(match.group(1)), int(match.group(2) or "00"))
        end = time(int(match.group(3)), int(match.group(4) or "00"))
        return start, end

    def _normalize_time(self, value: str) -> str | None:
        if not value:
            return None
        raw = value.lower().replace(".", ":").replace("-", ":")
        if "десять" in raw:
            return "10:00"
        if "девять" in raw:
            return "09:00"
        m = re.search(r"\b([01]?\d|2[0-3])(?::([0-5]\d))?\b", raw)
        if not m:
            return None
        hours = int(m.group(1))
        minutes = int(m.group(2) or "00")
        return f"{hours:02d}:{minutes:02d}"

    def _normalize_date(self, value: str, *, base_date: date) -> date | None:
        raw = value.strip().lower()
        if "послезавтра" in raw:
            return base_date + timedelta(days=2)
        if "завтра" in raw or "завтраш" in raw:
            return base_date + timedelta(days=1)
        if "сегодня" in raw or "сегодняш" in raw:
            return base_date

        iso = re.search(r"\b(\d{4})-(\d{2})-(\d{2})\b", raw)
        if iso:
            try:
                return date(int(iso.group(1)), int(iso.group(2)), int(iso.group(3)))
            except ValueError:
                return None

        months = {
            "января": 1,
            "январь": 1,
            "февраля": 2,
            "февраль": 2,
            "марта": 3,
            "март": 3,
            "апреля": 4,
            "апрель": 4,
            "мая": 5,
            "май": 5,
            "июня": 6,
            "июнь": 6,
            "июля": 7,
            "июль": 7,
            "августа": 8,
            "август": 8,
            "сентября": 9,
            "сентябрь": 9,
            "октября": 10,
            "октябрь": 10,
            "ноября": 11,
            "ноябрь": 11,
            "декабря": 12,
            "декабрь": 12,
        }
        month_pattern = "|".join(months)
        russian = re.search(rf"\b([0-3]?\d)\s+({month_pattern})(?:\s+(\d{{4}}))?\b", raw)
        if not russian:
            return None

        day = int(russian.group(1))
        month = months[russian.group(2)]
        year = int(russian.group(3)) if russian.group(3) else base_date.year
        try:
            parsed = date(year, month, day)
        except ValueError:
            return None
        if russian.group(3) is None and parsed < base_date:
            try:
                return date(year + 1, month, day)
            except ValueError:
                return parsed
        return parsed

    def _weekday_to_num(self, value: str) -> int | None:
        mapping = {
            "понедельник": 0,
            "вторник": 1,
            "среда": 2,
            "среду": 2,
            "четверг": 3,
            "пятница": 4,
            "пятницу": 4,
            "суббота": 5,
            "субботу": 5,
            "воскресенье": 6,
        }
        for token, num in mapping.items():
            if token in value:
                return num
        return None
