from datetime import date, datetime, timedelta, timezone

import pytest

from app.schemas.commands import DayReference, ReminderInput, resolve_default_run_at
from app.services.llm_service import LLMCommandValidationError, parse_assistant_command
from app.services.temporal_normalizer import TemporalNormalizer


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


def test_parse_delete_with_legacy_filter_status_key() -> None:
    payload = {"command": "delete_reminders", "mode": "filter", "filter_status": "done"}
    command = parse_assistant_command(payload)
    assert command.command == "delete_reminders"
    assert command.status == "done"


def test_parse_delete_with_legacy_id_key() -> None:
    payload = {"command": "delete_reminders", "mode": "filter", "id": 20}
    command = parse_assistant_command(payload)
    assert command.command == "delete_reminders"
    assert command.reminder_id == 20


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


def test_weekday_string_and_time_field_are_supported() -> None:
    payload = {
        "command": "create_reminders",
        "reminders": [
            {
                "text": "созвон с командой",
                "day_reference": "weekday",
                "weekday": "wednesday",
                "explicit_time_provided": True,
                "time": "10:30",
            }
        ],
    }
    command = parse_assistant_command(payload)
    reminder = command.reminders[0]
    assert reminder.weekday == 2
    now = datetime(2026, 2, 22, 11, 0, tzinfo=timezone.utc)
    resolved = resolve_default_run_at(reminder, now)
    assert resolved == datetime(2026, 2, 25, 10, 30, tzinfo=timezone.utc)


def test_temporal_normalizer_infers_today_from_text() -> None:
    payload = {
        "command": "create_reminders",
        "reminders": [
            {
                "text": "test",
                "run_at": "2024-06-05T12:15:00+03:00",
                "explicit_time_provided": True,
            }
        ],
    }
    command = parse_assistant_command(payload)
    normalizer = TemporalNormalizer(timezone="UTC")
    fixed = normalizer.normalize_command(
        command=command,
        user_text="Сегодня в 12:15 напомни, что я молодец",
        now=datetime(2026, 3, 5, 11, 58, tzinfo=timezone.utc),
    )
    reminder = fixed.reminders[0]
    assert reminder.day_reference == DayReference.today
    assert reminder.time_value == "12:15"
    assert reminder.run_at is None


@pytest.mark.parametrize(
    ("phrase", "expected_day_ref", "expected_time"),
    [
        ("Сегодня в 12:15 напомни позвонить", DayReference.today, "12:15"),
        ("Завтра в 10 купить молоко", DayReference.tomorrow, "10:00"),
        ("Послезавтра в 18:30 встреча", DayReference.day_after_tomorrow, "18:30"),
        ("В среду в 14 созвон", DayReference.weekday, "14:00"),
        ("Сегодня напомни отправить отчет", DayReference.today, None),
        ("Завтра напомни купить билеты", DayReference.tomorrow, None),
    ],
)
def test_temporal_normalizer_table_driven_relative_phrases(
    phrase: str,
    expected_day_ref: DayReference,
    expected_time: str | None,
) -> None:
    payload = {
        "command": "create_reminders",
        "reminders": [{"text": "task", "run_at": "2024-06-05T12:15:00+03:00", "explicit_time_provided": True}],
    }
    command = parse_assistant_command(payload)
    normalizer = TemporalNormalizer(timezone="UTC")
    fixed = normalizer.normalize_command(
        command=command,
        user_text=phrase,
        now=datetime(2026, 3, 9, 9, 0, tzinfo=timezone.utc),
    )
    reminder = fixed.reminders[0]
    assert reminder.day_reference == expected_day_ref
    if expected_time is not None:
        assert reminder.time_value == expected_time


def test_specific_date_legacy_field_is_accepted() -> None:
    payload = {
        "command": "create_reminders",
        "reminders": [
            {
                "text": "поздравить детей со свадьбой",
                "day_reference": "specific_date",
                "specific_date": "2026-03-10",
                "time": "10:00",
                "explicit_time_provided": True,
            }
        ],
    }
    command = parse_assistant_command(payload)
    reminder = command.reminders[0]
    assert reminder.day_reference == DayReference.specific_date
    assert reminder.date_value == date(2026, 3, 10)
    assert reminder.time_value == "10:00"


def test_day_reference_iso_date_string_is_normalized_to_specific_date() -> None:
    payload = {
        "command": "create_reminders",
        "reminders": [
            {
                "text": "поздравить маму с днем рождения",
                "day_reference": "2026-03-11",
                "explicit_time_provided": False,
            }
        ],
    }
    command = parse_assistant_command(payload)
    reminder = command.reminders[0]
    assert reminder.day_reference == DayReference.specific_date
    assert reminder.date_value == date(2026, 3, 11)


def test_temporal_normalizer_parses_russian_month_date() -> None:
    payload = {
        "command": "create_reminders",
        "reminders": [{"text": "поздравить маму", "run_at": "2026-03-09T09:00:00+00:00", "explicit_time_provided": True}],
    }
    command = parse_assistant_command(payload)
    normalizer = TemporalNormalizer(timezone="UTC")
    fixed = normalizer.normalize_command(
        command=command,
        user_text="10 марта в 9 поздравить маму",
        now=datetime(2026, 3, 9, 12, 0, tzinfo=timezone.utc),
    )
    reminder = fixed.reminders[0]
    assert reminder.day_reference == DayReference.specific_date
    assert reminder.date_value == date(2026, 3, 10)
    assert reminder.time_value == "09:00"


def test_naive_run_at_is_treated_as_local_time() -> None:
    now = datetime(2026, 3, 7, 19, 50, tzinfo=timezone(timedelta(hours=3)))
    reminder = ReminderInput(
        text="test",
        run_at=datetime(2026, 3, 11, 10, 0),
        explicit_time_provided=True,
    )
    resolved = resolve_default_run_at(reminder, now)
    assert resolved == datetime(2026, 3, 11, 10, 0, tzinfo=timezone(timedelta(hours=3)))
