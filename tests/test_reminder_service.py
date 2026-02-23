from datetime import datetime, timezone

from app.core.internal_reminders import INTERNAL_PRE_REMINDER_PREFIX
from app.schemas.commands import CreateRemindersCommand
from app.services.reminder_service import ReminderService


class FakeReminder:
    def __init__(self, idx: int, data: dict):
        self.id = idx
        self.text = data["text"]
        self.run_at = data["run_at"]
        self.recurrence_rule = data.get("recurrence_rule")
        self.series_id = data.get("series_id")


class FakeRepository:
    def __init__(self) -> None:
        self.saved_payload: list[dict] = []
        self.created_series: list[dict] = []

    async def create_many(self, items):
        self.saved_payload = list(items)
        return [FakeReminder(i + 1, item) for i, item in enumerate(items)]

    async def create_series(self, *, series_id: str, chat_id: int, source_text: str, recurrence_rule: str):
        self.created_series.append(
            {
                "series_id": series_id,
                "chat_id": chat_id,
                "source_text": source_text,
                "recurrence_rule": recurrence_rule,
            }
        )
        return None


async def test_create_multiple_with_default_time_rules() -> None:
    repo = FakeRepository()
    service = ReminderService(repo)
    cmd = CreateRemindersCommand.model_validate(
        {
            "command": "create_reminders",
            "reminders": [
                {"text": "Сегодня без времени", "day_reference": "today", "explicit_time_provided": False},
                {"text": "Завтра без времени", "day_reference": "tomorrow", "explicit_time_provided": False},
            ],
        }
    )
    now = datetime(2026, 2, 21, 10, 15, tzinfo=timezone.utc)
    created = await service.create_from_command(chat_id=123, command=cmd, now=now)

    assert len(created) == 2
    assert created[0].run_at == datetime(2026, 2, 21, 11, 0, tzinfo=timezone.utc)
    assert created[1].run_at == datetime(2026, 2, 22, 8, 0, tzinfo=timezone.utc)
    assert len(repo.saved_payload) == 3
    assert repo.saved_payload[1]["text"].startswith(INTERNAL_PRE_REMINDER_PREFIX)
    assert repo.saved_payload[1]["run_at"] == datetime(2026, 2, 22, 7, 0, tzinfo=timezone.utc)


async def test_create_with_recurrence_rule() -> None:
    repo = FakeRepository()
    service = ReminderService(repo)
    cmd = CreateRemindersCommand.model_validate(
        {
            "command": "create_reminders",
            "reminders": [
                {
                    "text": "Ежедневная задача",
                    "run_at": "2026-02-23T09:00:00+00:00",
                    "recurrence_rule": "FREQ=DAILY",
                    "explicit_time_provided": True,
                }
            ],
        }
    )
    now = datetime(2026, 2, 22, 10, 15, tzinfo=timezone.utc)
    created = await service.create_from_command(chat_id=123, command=cmd, now=now)
    assert len(created) == 7
    assert created[0].run_at == datetime(2026, 2, 23, 9, 0, tzinfo=timezone.utc)
    assert created[-1].run_at == datetime(2026, 3, 1, 9, 0, tzinfo=timezone.utc)
    assert created[0].recurrence_rule is None
    assert len(repo.saved_payload) == 14
    assert len(repo.created_series) == 1
    assert repo.created_series[0]["recurrence_rule"] == "FREQ=DAILY"
    assert repo.saved_payload[0]["series_id"] is not None
    assert repo.saved_payload[0]["text"].startswith(INTERNAL_PRE_REMINDER_PREFIX)
    assert repo.saved_payload[0]["run_at"] == datetime(2026, 2, 23, 8, 0, tzinfo=timezone.utc)


async def test_create_keeps_explicit_recurrence_until() -> None:
    repo = FakeRepository()
    service = ReminderService(repo)
    cmd = CreateRemindersCommand.model_validate(
        {
            "command": "create_reminders",
            "reminders": [
                {
                    "text": "Почасовой контроль",
                    "run_at": "2026-02-23T09:00:00+00:00",
                    "recurrence_rule": "FREQ=HOURLY;UNTIL=2026-02-23T15:00:00+00:00",
                    "explicit_time_provided": True,
                }
            ],
        }
    )
    now = datetime(2026, 2, 22, 10, 15, tzinfo=timezone.utc)
    created = await service.create_from_command(chat_id=123, command=cmd, now=now)
    assert len(created) == 24
    assert created[0].recurrence_rule is None
    assert len(repo.created_series) == 1


async def test_create_today_single_notification_only() -> None:
    repo = FakeRepository()
    service = ReminderService(repo)
    cmd = CreateRemindersCommand.model_validate(
        {
            "command": "create_reminders",
            "reminders": [
                {
                    "text": "Позвонить сегодня",
                    "run_at": "2026-02-21T16:00:00+00:00",
                    "explicit_time_provided": True,
                }
            ],
        }
    )
    now = datetime(2026, 2, 21, 10, 15, tzinfo=timezone.utc)
    created = await service.create_from_command(chat_id=123, command=cmd, now=now)

    assert len(created) == 1
    assert created[0].run_at == datetime(2026, 2, 21, 16, 0, tzinfo=timezone.utc)
