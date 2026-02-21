from datetime import datetime, timezone

from app.schemas.commands import CreateRemindersCommand
from app.services.reminder_service import ReminderService


class FakeReminder:
    def __init__(self, idx: int, data: dict):
        self.id = idx
        self.text = data["text"]
        self.run_at = data["run_at"]
        self.recurrence_rule = data.get("recurrence_rule")


class FakeRepository:
    def __init__(self) -> None:
        self.saved_payload: list[dict] = []

    async def create_many(self, items):
        self.saved_payload = list(items)
        return [FakeReminder(i + 1, item) for i, item in enumerate(items)]


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
    created = await service.create_from_command(chat_id=123, command=cmd)
    assert len(created) == 1
    assert created[0].recurrence_rule == "FREQ=DAILY"
