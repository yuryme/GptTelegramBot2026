from datetime import datetime
from zoneinfo import ZoneInfo

import pytest

from app.services.llm_service import parse_semantic_command_draft
from app.services.recurring_end_policy import ensure_until_for_rrule
from app.services.semantic_draft_compiler import SemanticDraftCompilationError, SemanticDraftCompiler


def _compile_rule(item: dict) -> str | None:
    payload = {"intent": "create_reminders", "create_items": [item], "passthrough_command": None}
    draft = parse_semantic_command_draft(payload)
    cmd = SemanticDraftCompiler().compile_to_command(
        draft=draft,
        now=datetime(2026, 5, 24, 12, 0, tzinfo=ZoneInfo("Europe/Moscow")),
    )
    return cmd.reminders[0].recurrence_rule


def test_default_daily_gets_end_of_week() -> None:
    rule, _ = ensure_until_for_rrule(
        recurrence_rule="FREQ=DAILY",
        start_local=datetime(2026, 3, 10, 9, 0, tzinfo=ZoneInfo("Europe/Moscow")),
    )
    assert "UNTIL=2026-03-15T09:00:59+03:00" in rule


def test_default_hourly_gets_end_of_same_day() -> None:
    rule, _ = ensure_until_for_rrule(
        recurrence_rule="FREQ=HOURLY",
        start_local=datetime(2026, 3, 10, 10, 0, tzinfo=ZoneInfo("Europe/Moscow")),
    )
    assert "UNTIL=2026-03-10T23:59:59+03:00" in rule


def test_explicit_date_until_is_kept() -> None:
    rule = _compile_rule(
        {
            "reminder_text": "пить воду",
            "day_expression": None,
            "time_expression": "в 9",
            "date_expression": None,
            "recurrence_expression": "каждый день",
            "recurrence_until_expression": "2026-04-01",
            "recurrence_interval": None,
            "pre_reminder_expression": None,
            "raw_context": "напоминай каждый день в 9 до 1 апреля",
        }
    )
    assert rule is not None
    assert "UNTIL=2026-04-01T23:59:59" in rule


def test_period_end_hint_is_resolved_to_month_end() -> None:
    rule = _compile_rule(
        {
            "reminder_text": "пить воду",
            "day_expression": None,
            "time_expression": "в 9",
            "date_expression": None,
            "recurrence_expression": "каждый день",
            "recurrence_until_expression": "до конца месяца",
            "recurrence_interval": None,
            "pre_reminder_expression": None,
            "raw_context": "напоминай каждый день в 9 до конца месяца",
        }
    )
    assert "X_END_INTENT=until_period_end" in (rule or "")
    resolved, _ = ensure_until_for_rrule(
        recurrence_rule=rule or "",
        start_local=datetime(2026, 3, 10, 9, 0, tzinfo=ZoneInfo("Europe/Moscow")),
    )
    assert "UNTIL=2026-03-31T09:00:59+03:00" in resolved


def test_interval_extraction_for_every_2_weeks() -> None:
    rule = _compile_rule(
        {
            "reminder_text": "отчёт",
            "day_expression": "по средам",
            "time_expression": "в 10",
            "date_expression": None,
            "recurrence_expression": "каждые 2 недели",
            "recurrence_until_expression": None,
            "recurrence_interval": None,
            "pre_reminder_expression": None,
            "raw_context": "напоминай каждые 2 недели по средам в 10",
        }
    )
    assert "FREQ=WEEKLY" in (rule or "")
    assert "INTERVAL=2" in (rule or "")


def test_interval_extraction_for_every_2_hours() -> None:
    rule = _compile_rule(
        {
            "reminder_text": "пить воду",
            "day_expression": "сегодня",
            "time_expression": "в 10",
            "date_expression": None,
            "recurrence_expression": "каждые 2 часа",
            "recurrence_until_expression": None,
            "recurrence_interval": None,
            "pre_reminder_expression": None,
            "raw_context": "напоминай каждые 2 часа",
        }
    )
    assert "FREQ=HOURLY" in (rule or "")
    assert "INTERVAL=2" in (rule or "")


def test_interval_extraction_for_every_30_minutes_in_time_range() -> None:
    rule = _compile_rule(
        {
            "reminder_text": "проверить воду",
            "day_expression": "завтра",
            "time_expression": None,
            "date_expression": None,
            "period_start_expression": "завтра с 10:00",
            "period_end_expression": "завтра до 12:00",
            "recurrence_expression": "каждые 30 минут",
            "recurrence_until_expression": "завтра с 10:00 до 12:00",
            "recurrence_interval": None,
            "pre_reminder_expression": None,
            "raw_context": "создай напоминание каждые 30 минут завтра с 10 до 12 проверить воду",
        }
    )
    assert rule == "FREQ=MINUTELY;INTERVAL=30;UNTIL=2026-05-25T12:00:00"


def test_interval_extraction_for_hour_word_time_range() -> None:
    rule = _compile_rule(
        {
            "reminder_text": "периодический тест",
            "day_expression": "сегодня",
            "time_expression": None,
            "date_expression": None,
            "period_start_expression": "16 часов",
            "period_end_expression": "17 часов",
            "recurrence_expression": "каждые 15 минут",
            "recurrence_until_expression": None,
            "recurrence_interval": 15,
            "pre_reminder_expression": None,
            "raw_context": "Сегодня с 16 часов до 17 часов каждые 15 минут напоминание периодический тест.",
        }
    )
    assert rule == "FREQ=MINUTELY;INTERVAL=15;UNTIL=2026-05-24T17:00:00"


def test_interval_extraction_for_every_2_months() -> None:
    rule = _compile_rule(
        {
            "reminder_text": "платеж",
            "day_expression": None,
            "time_expression": "в 9",
            "date_expression": None,
            "recurrence_expression": "каждые 2 месяца",
            "recurrence_until_expression": None,
            "recurrence_interval": None,
            "pre_reminder_expression": None,
            "raw_context": "напоминай каждые 2 месяца 5 числа в 9",
        }
    )
    assert "FREQ=MONTHLY" in (rule or "")
    assert "INTERVAL=2" in (rule or "")


def test_ambiguous_until_expression_raises() -> None:
    payload = {
        "intent": "create_reminders",
        "create_items": [
            {
                "reminder_text": "пить воду",
                "day_expression": None,
                "time_expression": "в 9",
                "date_expression": None,
                "recurrence_expression": "каждый день",
                "recurrence_until_expression": "до следующей недели",
                "recurrence_interval": None,
                "pre_reminder_expression": None,
                "raw_context": "напоминай каждый день в 9 до следующей недели",
            }
        ],
        "passthrough_command": None,
    }
    draft = parse_semantic_command_draft(payload)
    with pytest.raises(SemanticDraftCompilationError):
        SemanticDraftCompiler().compile_to_command(draft=draft)
