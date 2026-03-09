from datetime import datetime, timezone

import pytest

from app.schemas.commands import DayReference
from app.services.llm_service import parse_semantic_command_draft
from app.services.semantic_draft_compiler import SemanticDraftCompiler
from app.services.temporal_normalizer import TemporalNormalizer


def _compile_and_normalize(payload: dict):
    draft = parse_semantic_command_draft(payload)
    compiler = SemanticDraftCompiler()
    command = compiler.compile_to_command(draft=draft)
    normalizer = TemporalNormalizer(timezone="UTC")
    return normalizer.normalize_command(
        command=command,
        user_text=payload["create_items"][0].get("raw_context") or payload["create_items"][0]["reminder_text"],
        now=datetime(2026, 3, 10, 12, 0, tzinfo=timezone.utc),
    )


@pytest.mark.parametrize(
    ("payload", "expected"),
    [
        (
            {
                "intent": "create_reminders",
                "create_items": [
                    {
                        "reminder_text": "сегодня едем к Олегу",
                        "day_expression": "в среду",
                        "time_expression": "в десять утра",
                        "date_expression": None,
                        "recurrence_expression": None,
                        "raw_context": "Напомни в среду в десять утра, сегодня едем к Олегу",
                    }
                ],
                "passthrough_command": None,
            },
            {"day_reference": DayReference.weekday, "weekday": 2, "time": "10:00"},
        ),
        (
            {
                "intent": "create_reminders",
                "create_items": [
                    {
                        "reminder_text": "что встреча в пятницу в 15",
                        "day_expression": "завтра",
                        "time_expression": None,
                        "date_expression": None,
                        "recurrence_expression": None,
                        "raw_context": "Завтра напомни, что встреча в пятницу в 15",
                    }
                ],
                "passthrough_command": None,
            },
            {"day_reference": DayReference.tomorrow, "weekday": None, "time": None},
        ),
        (
            {
                "intent": "create_reminders",
                "create_items": [
                    {
                        "reminder_text": "поздравить маму",
                        "day_expression": None,
                        "time_expression": "в 9 утра",
                        "date_expression": "2026-03-10",
                        "recurrence_expression": None,
                        "raw_context": "Напомни 10 марта поздравить маму в 9 утра",
                    }
                ],
                "passthrough_command": None,
            },
            {"day_reference": DayReference.specific_date, "weekday": None, "time": "09:00"},
        ),
        (
            {
                "intent": "create_reminders",
                "create_items": [
                    {
                        "reminder_text": "купить лекарства, когда буду у врача",
                        "day_expression": None,
                        "time_expression": None,
                        "date_expression": None,
                        "recurrence_expression": None,
                        "raw_context": "Напомни купить лекарства, когда буду у врача",
                    }
                ],
                "passthrough_command": None,
            },
            {"day_reference": DayReference.today, "weekday": None, "time": None},
        ),
        (
            {
                "intent": "create_reminders",
                "create_items": [
                    {
                        "reminder_text": "созвон с командой, встреча в тексте не должна стать датой",
                        "day_expression": "в пятницу",
                        "time_expression": None,
                        "date_expression": None,
                        "recurrence_expression": None,
                        "raw_context": "Напомни в пятницу созвон с командой, встреча в тексте не должна стать датой",
                    }
                ],
                "passthrough_command": None,
            },
            {"day_reference": DayReference.weekday, "weekday": 4, "time": None},
        ),
    ],
)
def test_semantic_draft_and_compiled_command_for_mandatory_cases(payload: dict, expected: dict) -> None:
    draft = parse_semantic_command_draft(payload)
    assert draft.intent == "create_reminders"
    assert draft.create_items[0].reminder_text

    command = _compile_and_normalize(payload)
    reminder = command.reminders[0]
    assert reminder.day_reference == expected["day_reference"]
    assert reminder.weekday == expected["weekday"]
    if expected["time"] is not None:
        assert reminder.time_value == expected["time"]


def test_semantic_draft_for_list_passthrough() -> None:
    payload = {
        "intent": "list_reminders",
        "create_items": [],
        "passthrough_command": {"command": "list_reminders", "mode": "today"},
    }
    draft = parse_semantic_command_draft(payload)
    compiler = SemanticDraftCompiler()
    command = compiler.compile_to_command(draft=draft)
    assert command.command == "list_reminders"
    assert command.mode == "today"


@pytest.mark.parametrize(
    ("reminder_text", "raw_context", "expected"),
    [
        ("что сегодня начинаем новую неделю", "Напомни, что сегодня начинаем новую неделю", "сегодня начинаем новую неделю"),
        ("что завтра нужно купить торт", "напомни что завтра нужно купить торт", "завтра нужно купить торт"),
        ("что завтра нужно купить торт", None, "завтра нужно купить торт"),
        ("напомни: позвонить родителям", "напомни: позвонить родителям", "позвонить родителям"),
        ("чтобы отправить отчет", "напомни чтобы отправить отчет", "отправить отчет"),
        ("что важно в тексте", "сегодня обсуждаем что важно в тексте", "что важно в тексте"),
    ],
)
def test_wrapper_marker_cleanup_for_reminder_text(reminder_text: str, raw_context: str | None, expected: str) -> None:
    payload = {
        "intent": "create_reminders",
        "create_items": [
            {
                "reminder_text": reminder_text,
                "day_expression": "сегодня",
                "time_expression": None,
                "date_expression": None,
                "recurrence_expression": None,
                "raw_context": raw_context,
            }
        ],
        "passthrough_command": None,
    }
    draft = parse_semantic_command_draft(payload)
    compiler = SemanticDraftCompiler()
    command = compiler.compile_to_command(draft=draft)
    assert command.reminders[0].text == expected
