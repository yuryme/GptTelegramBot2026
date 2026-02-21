from datetime import datetime, timezone

from app.schemas.commands import ListRemindersCommand
from app.services.reminder_service import ReminderService


class FakeListRecord:
    def __init__(self, idx: int, status: str, text: str, run_at: datetime, recurrence_rule: str | None = None):
        self.id = idx
        self.status = status
        self.text = text
        self.run_at = run_at
        self.recurrence_rule = recurrence_rule


class FakeListRepository:
    def __init__(self) -> None:
        self.last_args = {}
        self.result: list[FakeListRecord] = []

    async def list_items(self, chat_id: int, **kwargs):
        self.last_args = {"chat_id": chat_id, **kwargs}
        return self.result


async def test_list_all_passes_no_filters() -> None:
    repo = FakeListRepository()
    repo.result = [FakeListRecord(1, "pending", "A", datetime(2026, 2, 21, 10, 0, tzinfo=timezone.utc))]
    service = ReminderService(repo)  # type: ignore[arg-type]

    cmd = ListRemindersCommand.model_validate({"command": "list_reminders", "mode": "all"})
    data = await service.list_from_command(chat_id=100, command=cmd)

    assert len(data) == 1
    assert repo.last_args["status"] is None
    assert repo.last_args["search_text"] is None


async def test_list_today_sets_day_bounds() -> None:
    repo = FakeListRepository()
    service = ReminderService(repo)  # type: ignore[arg-type]
    now = datetime(2026, 2, 21, 10, 15, tzinfo=timezone.utc)
    cmd = ListRemindersCommand.model_validate({"command": "list_reminders", "mode": "today"})

    await service.list_from_command(chat_id=200, command=cmd, now=now)

    assert repo.last_args["from_dt"] == datetime(2026, 2, 21, 0, 0, tzinfo=timezone.utc)
    assert repo.last_args["to_dt"] == datetime(2026, 2, 21, 23, 59, 59, 999999, tzinfo=timezone.utc)


async def test_list_status_search_range_forwarded() -> None:
    repo = FakeListRepository()
    service = ReminderService(repo)  # type: ignore[arg-type]
    cmd = ListRemindersCommand.model_validate(
        {
            "command": "list_reminders",
            "mode": "range",
            "status": "pending",
            "search_text": "клиент",
            "from_dt": "2026-02-21T00:00:00+00:00",
            "to_dt": "2026-02-22T00:00:00+00:00",
        }
    )

    await service.list_from_command(chat_id=300, command=cmd)

    assert repo.last_args["status"] == "pending"
    assert repo.last_args["search_text"] == "клиент"
    assert repo.last_args["from_dt"] == datetime(2026, 2, 21, 0, 0, tzinfo=timezone.utc)
    assert repo.last_args["to_dt"] == datetime(2026, 2, 22, 0, 0, tzinfo=timezone.utc)

