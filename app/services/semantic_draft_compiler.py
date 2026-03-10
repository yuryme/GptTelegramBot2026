from __future__ import annotations

import re
from datetime import date, datetime, time, timedelta

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
from app.schemas.semantic_draft import CreateReminderDraft, SemanticCommandDraft
from app.services.recurring_end_policy import detect_end_intent, extract_interval_from_text


class SemanticDraftCompilationError(ValueError):
    pass


class SemanticDraftCompiler:
    def compile_to_command(self, *, draft: SemanticCommandDraft) -> AssistantCommand:
        if draft.intent == "create_reminders":
            if not draft.create_items:
                raise SemanticDraftCompilationError("create draft must contain at least one create item")
            reminders = [plan.reminder_payload for plan in self.compile_create_plans(draft=draft)]
            return assistant_command_adapter.validate_python({"command": "create_reminders", "reminders": reminders})

        if draft.passthrough_command is None:
            raise SemanticDraftCompilationError("passthrough_command is required for non-create intents")
        return assistant_command_adapter.validate_python(draft.passthrough_command)

    def compile_create_plans(self, *, draft: SemanticCommandDraft) -> list[CompiledCreateReminderPlan]:
        if draft.intent != "create_reminders":
            return []
        return [self._compile_create_item(item) for item in draft.create_items]

    def _compile_create_item(self, item: CreateReminderDraft) -> CompiledCreateReminderPlan:
        cleaned_text = self._cleanup_wrapper_markers(
            reminder_text=item.reminder_text,
            raw_context=item.raw_context,
            day_expression=item.day_expression,
            time_expression=item.time_expression,
            date_expression=item.date_expression,
            recurrence_expression=item.recurrence_expression,
        )
        result: dict[str, object] = {
            "text": cleaned_text,
            "explicit_time_provided": False,
        }

        day_expr = (item.day_expression or "").strip().lower()
        date_expr = (item.date_expression or "").strip()
        time_expr = (item.time_expression or "").strip()

        day_reference: str | None = None
        if day_expr:
            if "послезавтра" in day_expr:
                day_reference = "day_after_tomorrow"
            elif "завтра" in day_expr:
                day_reference = "tomorrow"
            elif "сегодня" in day_expr:
                day_reference = "today"
            elif self._weekday_to_num(day_expr) is not None:
                day_reference = "weekday"
                result["weekday"] = self._weekday_to_num(day_expr)

        if date_expr:
            day_reference = "specific_date"
            result["date_value"] = date_expr

        if day_reference is not None:
            result["day_reference"] = day_reference
        else:
            result["day_reference"] = "today"

        normalized_time = self._normalize_time(time_expr)
        if normalized_time is not None:
            result["time"] = normalized_time
            result["explicit_time_provided"] = True

        recurrence = self._compile_recurrence_policy(item)
        if recurrence.legacy_rule:
            result["recurrence_rule"] = recurrence.legacy_rule

        display = self._compile_display_policy(item=item, user_time=normalized_time)
        return CompiledCreateReminderPlan(reminder_payload=result, recurrence=recurrence, display=display)

    def _compile_recurrence_policy(self, item: CreateReminderDraft) -> InternalRecurrencePolicy:
        raw = (item.recurrence_expression or "").strip().lower()
        interval = item.recurrence_interval or extract_interval_from_text(item.recurrence_expression) or 1
        weekdays: list[int] = []
        month_day: int | None = None
        kind = RecurrenceKind.one_time
        legacy_rule: str | None = None

        if raw:
            if raw.startswith("freq="):
                legacy_rule = item.recurrence_expression.strip()
                return self._build_policy_from_rrule(legacy_rule)

            if any(token in raw for token in ("каждый день", "ежеднев", "every day")):
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

        until_dt = self._parse_recurrence_until(item.recurrence_until_expression)
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

        kind = RecurrenceKind.one_time
        if freq == "DAILY":
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
    ) -> str:
        freq = {
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
