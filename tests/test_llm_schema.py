from datetime import date, datetime, timezone

import pytest

from app.schemas.commands import DayReference, ReminderInput, resolve_default_run_at
from app.services.llm_service import LLMCommandValidationError, parse_assistant_command


def test_parse_valid_create_command() -> None:
    payload = {
        "command": "create_reminders",
        "reminders": [
            {
                "text": "Позвонить клиенту",
                "day_reference": "tomorrow",
                "explicit_time_provided": False,
            }
        ],
    }
    command = parse_assistant_command(payload)
    assert command.command == "create_reminders"
    assert command.reminders[0].day_reference == DayReference.tomorrow


def test_parse_invalid_json_raises() -> None:
    with pytest.raises(LLMCommandValidationError):
        parse_assistant_command("not-json")


def test_parse_invalid_schema_raises() -> None:
    with pytest.raises(LLMCommandValidationError):
        parse_assistant_command({"command": "create_reminders", "reminders": []})


def test_today_without_time_uses_next_hour() -> None:
    now = datetime(2026, 2, 21, 10, 15, tzinfo=timezone.utc)
    reminder = ReminderInput(text="Тест", day_reference=DayReference.today, explicit_time_provided=False)
    resolved = resolve_default_run_at(reminder, now)
    assert resolved == datetime(2026, 2, 21, 11, 0, tzinfo=timezone.utc)


def test_future_day_without_time_uses_8am() -> None:
    now = datetime(2026, 2, 21, 10, 15, tzinfo=timezone.utc)
    reminder = ReminderInput(text="Тест", day_reference=DayReference.tomorrow, explicit_time_provided=False)
    resolved = resolve_default_run_at(reminder, now)
    assert resolved == datetime(2026, 2, 22, 8, 0, tzinfo=timezone.utc)


def test_specific_date_without_time_uses_8am() -> None:
    now = datetime(2026, 2, 21, 10, 15, tzinfo=timezone.utc)
    reminder = ReminderInput(
        text="Тест",
        day_reference=DayReference.specific_date,
        date_value=date(2026, 2, 23),
        explicit_time_provided=False,
    )
    resolved = resolve_default_run_at(reminder, now)
    assert resolved == datetime(2026, 2, 23, 8, 0, tzinfo=timezone.utc)

