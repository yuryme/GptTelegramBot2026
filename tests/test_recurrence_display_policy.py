from app.schemas.internal_policies import PreReminderMode, RecurrenceKind
from app.services.llm_service import parse_semantic_command_draft
from app.services.semantic_draft_compiler import SemanticDraftCompiler


def _compile_plan(item: dict):
    payload = {
        "intent": "create_reminders",
        "create_items": [item],
        "passthrough_command": None,
    }
    draft = parse_semantic_command_draft(payload)
    compiler = SemanticDraftCompiler()
    plans = compiler.compile_create_plans(draft=draft)
    assert len(plans) == 1
    return plans[0]


def test_daily_recurrence_policy() -> None:
    plan = _compile_plan(
        {
            "reminder_text": "пить воду",
            "day_expression": None,
            "time_expression": "в 9",
            "date_expression": None,
            "recurrence_expression": "каждый день",
            "recurrence_until_expression": None,
            "recurrence_interval": None,
            "pre_reminder_expression": None,
            "raw_context": "Напоминай каждый день в 9 пить воду",
        }
    )
    assert plan.recurrence.kind == RecurrenceKind.daily
    assert plan.recurrence.legacy_rule == "FREQ=DAILY"
    assert plan.display.pre_reminder_mode == PreReminderMode.auto


def test_weekdays_without_pre_reminder_policy() -> None:
    plan = _compile_plan(
        {
            "reminder_text": "делать зарядку",
            "day_expression": None,
            "time_expression": "в 8",
            "date_expression": None,
            "recurrence_expression": "по будням",
            "recurrence_until_expression": None,
            "recurrence_interval": None,
            "pre_reminder_expression": "без преднапоминания",
            "raw_context": "Напоминай по будням в 8 без преднапоминания",
        }
    )
    assert plan.recurrence.kind == RecurrenceKind.weekly
    assert plan.recurrence.weekdays == [0, 1, 2, 3, 4]
    assert plan.display.pre_reminder_mode == PreReminderMode.disabled


def test_multi_weekday_recurrence_policy() -> None:
    plan = _compile_plan(
        {
            "reminder_text": "о тренировке",
            "day_expression": None,
            "time_expression": "в 19",
            "date_expression": None,
            "recurrence_expression": "каждый вторник и четверг",
            "recurrence_until_expression": None,
            "recurrence_interval": None,
            "pre_reminder_expression": None,
            "raw_context": "Напоминай каждый вторник и четверг в 19 о тренировке",
        }
    )
    assert plan.recurrence.kind == RecurrenceKind.weekly
    assert plan.recurrence.weekdays == [1, 3]


def test_one_time_with_one_hour_pre_reminder() -> None:
    plan = _compile_plan(
        {
            "reminder_text": "встреча",
            "day_expression": "завтра",
            "time_expression": "в 18",
            "date_expression": None,
            "recurrence_expression": None,
            "recurrence_until_expression": None,
            "recurrence_interval": None,
            "pre_reminder_expression": "за час до",
            "raw_context": "Напомни завтра в 18 и за час до этого",
        }
    )
    assert plan.recurrence.kind == RecurrenceKind.one_time
    assert plan.display.pre_reminder_mode == PreReminderMode.minutes_before
    assert plan.display.pre_reminder_minutes == 60


def test_daily_until_end_date_policy() -> None:
    plan = _compile_plan(
        {
            "reminder_text": "пить воду",
            "day_expression": None,
            "time_expression": "в 9",
            "date_expression": None,
            "recurrence_expression": "каждый день",
            "recurrence_until_expression": "2026-03-31",
            "recurrence_interval": None,
            "pre_reminder_expression": None,
            "raw_context": "Напоминай каждый день в 9 до конца месяца",
        }
    )
    assert plan.recurrence.kind == RecurrenceKind.daily
    assert "UNTIL=2026-03-31T23:59:59" in (plan.recurrence.legacy_rule or "")

