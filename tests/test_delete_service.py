import pytest
from datetime import datetime, timezone

from app.schemas.commands import DeleteRemindersCommand
from app.services.reminder_service import ReminderService


class FakeDeleteRecord:
    def __init__(self, idx: int, status: str, text: str, run_at: datetime):
        self.id = idx
        self.status = status
        self.text = text
        self.run_at = run_at
        self.recurrence_rule = None


class FakeDeleteRepository:
    def __init__(self) -> None:
        self.filter_calls = []
        self.last_n_calls = []
        self.deleted_ids = []
        self.filter_result = []
        self.last_n_result = []

    async def list_items(self, chat_id: int, **kwargs):
        self.filter_calls.append((chat_id, kwargs))
        return self.filter_result

    async def list_last_n(self, chat_id: int, n: int, **kwargs):
        self.last_n_calls.append((chat_id, n, kwargs))
        return self.last_n_result

    async def delete_by_ids(self, reminder_ids: list[int]) -> int:
        self.deleted_ids = list(reminder_ids)
        return len(reminder_ids)


def test_delete_schema_requires_last_n_for_last_mode() -> None:
    with pytest.raises(Exception):
        DeleteRemindersCommand.model_validate({"command": "delete_reminders", "mode": "last_n"})


def test_delete_schema_blocks_implicit_delete_all() -> None:
    with pytest.raises(Exception):
        DeleteRemindersCommand.model_validate({"command": "delete_reminders", "mode": "filter"})


async def test_delete_by_filter() -> None:
    repo = FakeDeleteRepository()
    repo.filter_result = [
        FakeDeleteRecord(1, "pending", "Позвонить", datetime(2026, 2, 23, 9, 0, tzinfo=timezone.utc))
    ]
    service = ReminderService(repo)  # type: ignore[arg-type]
    cmd = DeleteRemindersCommand.model_validate(
        {
            "command": "delete_reminders",
            "mode": "filter",
            "status": "pending",
            "search_text": "Позвонить",
        }
    )
    result = await service.delete_from_command(chat_id=1, command=cmd)
    assert result.deleted_count == 1
    assert repo.deleted_ids == [1]
    assert repo.filter_calls[0][1]["status"] == "pending"


async def test_delete_last_n() -> None:
    repo = FakeDeleteRepository()
    repo.last_n_result = [
        FakeDeleteRecord(10, "pending", "A", datetime(2026, 2, 24, 9, 0, tzinfo=timezone.utc)),
        FakeDeleteRecord(11, "pending", "B", datetime(2026, 2, 24, 10, 0, tzinfo=timezone.utc)),
    ]
    service = ReminderService(repo)  # type: ignore[arg-type]
    cmd = DeleteRemindersCommand.model_validate(
        {"command": "delete_reminders", "mode": "last_n", "last_n": 2}
    )
    result = await service.delete_from_command(chat_id=1, command=cmd)
    assert result.deleted_count == 2
    assert repo.deleted_ids == [10, 11]
    assert repo.last_n_calls[0][1] == 2


async def test_delete_all_requires_explicit_confirmation() -> None:
    repo = FakeDeleteRepository()
    repo.filter_result = [
        FakeDeleteRecord(1, "pending", "A", datetime(2026, 2, 24, 9, 0, tzinfo=timezone.utc)),
    ]
    service = ReminderService(repo)  # type: ignore[arg-type]
    cmd = DeleteRemindersCommand.model_validate(
        {"command": "delete_reminders", "mode": "filter", "confirm_delete_all": True}
    )
    result = await service.delete_from_command(chat_id=1, command=cmd)
    assert result.deleted_count == 1
    assert repo.deleted_ids == [1]
