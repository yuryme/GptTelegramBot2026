from __future__ import annotations

import re

from app.schemas.commands import AssistantCommand, assistant_command_adapter
from app.schemas.semantic_draft import SemanticCommandDraft


class SemanticDraftCompilationError(ValueError):
    pass


class SemanticDraftCompiler:
    def compile_to_command(self, *, draft: SemanticCommandDraft) -> AssistantCommand:
        if draft.intent == "create_reminders":
            if not draft.create_items:
                raise SemanticDraftCompilationError("create draft must contain at least one create item")
            reminders: list[dict[str, object]] = []
            for item in draft.create_items:
                reminder = self._compile_create_item(item)
                reminders.append(reminder)
            return assistant_command_adapter.validate_python({"command": "create_reminders", "reminders": reminders})

        if draft.passthrough_command is None:
            raise SemanticDraftCompilationError("passthrough_command is required for non-create intents")
        return assistant_command_adapter.validate_python(draft.passthrough_command)

    def _compile_create_item(self, item) -> dict[str, object]:
        result: dict[str, object] = {
            "text": item.reminder_text.strip(),
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

        if item.recurrence_expression:
            result["recurrence_rule"] = item.recurrence_expression.strip()

        return result

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
