from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone

import pytest

from app.core.internal_reminders import build_pre_reminder_text
from app.services.reminder_dispatcher import compute_next_run_at, dispatch_due_with_repository


@dataclass
class FakeReminder:
    id: int
    chat_id: int
    text: str
    run_at: datetime | None = None
    recurrence_rule: str | None = None


class FakeRepo:
    def __init__(self, items):
        self.items = items
        self.done_ids: list[int] = []
        self.rescheduled: list[tuple[int, datetime]] = []

    async def list_due_pending(self, until_dt: datetime, limit: int = 100):
        return self.items[:limit]

    async def mark_done(self, reminder_ids: list[int]) -> int:
        self.done_ids = reminder_ids
        return len(reminder_ids)

    async def reschedule(self, reminder_id: int, next_run_at: datetime) -> int:
        self.rescheduled.append((reminder_id, next_run_at))
        return 1


class FakeBot:
    def __init__(self, fail_chat_id: int | None = None):
        self.fail_chat_id = fail_chat_id
        self.sent: list[tuple[int, str]] = []

    async def send_message(self, chat_id: int, text: str):
        if self.fail_chat_id is not None and chat_id == self.fail_chat_id:
            raise RuntimeError("send failed")
        self.sent.append((chat_id, text))


@pytest.mark.asyncio
async def test_dispatch_due_sends_and_marks_done() -> None:
    repo = FakeRepo([FakeReminder(id=1, chat_id=42, text="buy milk", run_at=datetime(2026, 2, 22, 10, 40, tzinfo=timezone.utc))])
    bot = FakeBot()

    sent_count = await dispatch_due_with_repository(
        repository=repo,
        bot=bot,
        now=datetime(2026, 2, 22, 10, 40, tzinfo=timezone.utc),
    )

    assert sent_count == 1
    assert repo.done_ids == [1]
    assert repo.rescheduled == []
    assert bot.sent == [(42, "Напоминание: buy milk")]


@pytest.mark.asyncio
async def test_dispatch_due_skips_failed_send() -> None:
    repo = FakeRepo(
        [
            FakeReminder(id=1, chat_id=1, text="a", run_at=datetime(2026, 2, 22, 10, 40, tzinfo=timezone.utc)),
            FakeReminder(id=2, chat_id=2, text="b", run_at=datetime(2026, 2, 22, 10, 40, tzinfo=timezone.utc)),
        ]
    )
    bot = FakeBot(fail_chat_id=2)

    sent_count = await dispatch_due_with_repository(
        repository=repo,
        bot=bot,
        now=datetime(2026, 2, 22, 10, 40, tzinfo=timezone.utc),
    )

    assert sent_count == 1
    assert repo.done_ids == [1]
    assert repo.rescheduled == []
    assert bot.sent == [(1, "Напоминание: a")]


@pytest.mark.asyncio
async def test_dispatch_due_reschedules_daily_rule() -> None:
    item = FakeReminder(
        id=5,
        chat_id=7,
        text="daily",
        run_at=datetime(2026, 2, 22, 10, 40, tzinfo=timezone.utc),
        recurrence_rule="FREQ=DAILY",
    )
    repo = FakeRepo([item])
    bot = FakeBot()

    sent_count = await dispatch_due_with_repository(repository=repo, bot=bot, now=item.run_at)

    assert sent_count == 1
    assert repo.done_ids == []
    assert len(repo.rescheduled) == 1
    rid, next_run = repo.rescheduled[0]
    assert rid == 5
    assert next_run == datetime(2026, 2, 23, 10, 40, tzinfo=timezone.utc)


@pytest.mark.asyncio
async def test_dispatch_strips_internal_prefix_in_user_message() -> None:
    repo = FakeRepo(
        [
            FakeReminder(
                id=1,
                chat_id=42,
                text=build_pre_reminder_text("buy milk"),
                run_at=datetime(2026, 2, 22, 10, 40, tzinfo=timezone.utc),
            )
        ]
    )
    bot = FakeBot()

    await dispatch_due_with_repository(repository=repo, bot=bot, now=datetime(2026, 2, 22, 10, 40, tzinfo=timezone.utc))
    assert bot.sent == [(42, "Напоминание: buy milk")]


def test_compute_next_run_at_hourly_within_until() -> None:
    current = datetime(2026, 2, 23, 10, 0, tzinfo=timezone.utc)
    rule = "FREQ=HOURLY;UNTIL=2026-02-23T12:00:00+00:00"
    assert compute_next_run_at(current, rule) == datetime(2026, 2, 23, 11, 0, tzinfo=timezone.utc)


def test_compute_next_run_at_returns_none_after_until() -> None:
    current = datetime(2026, 2, 23, 12, 0, tzinfo=timezone.utc)
    rule = "FREQ=HOURLY;UNTIL=2026-02-23T12:00:00+00:00"
    assert compute_next_run_at(current, rule) is None
