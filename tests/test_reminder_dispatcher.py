from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone

import pytest

from app.core.internal_reminders import build_pre_reminder_text, is_internal_pre_reminder
from app.services.reminder_dispatcher import dispatch_due_with_repository
from app.services.recurrence import compute_next_run_at


@dataclass
class FakeReminder:
    id: int
    chat_id: int
    text: str
    run_at: datetime
    recurrence_rule: str | None = None
    series_id: str | None = None
    status: str = "pending"


class InMemoryRepo:
    def __init__(self, items: list[FakeReminder]):
        self.items = items
        self.done_ids: list[int] = []
        self.rescheduled: list[tuple[int, datetime]] = []
        self.created_pre: list[FakeReminder] = []
        self._next_id = max((item.id for item in items), default=0) + 1

    async def list_due_pending(self, until_dt: datetime, limit: int = 100):
        due = [item for item in self.items if item.status == "pending" and item.run_at <= until_dt]
        due.sort(key=lambda x: (x.run_at, x.id))
        return due[:limit]

    async def mark_done(self, reminder_ids: list[int]) -> int:
        self.done_ids.extend(reminder_ids)
        done_set = set(reminder_ids)
        for item in self.items:
            if item.id in done_set:
                item.status = "done"
        return len(reminder_ids)

    async def reschedule(self, reminder_id: int, next_run_at: datetime) -> int:
        for item in self.items:
            if item.id == reminder_id:
                item.run_at = next_run_at
                item.status = "pending"
                self.rescheduled.append((reminder_id, next_run_at))
                return 1
        return 0

    async def create_one(
        self,
        chat_id: int,
        text: str,
        run_at: datetime,
        recurrence_rule: str | None = None,
        series_id: str | None = None,
    ):
        created = FakeReminder(
            id=self._next_id,
            chat_id=chat_id,
            text=text,
            run_at=run_at,
            recurrence_rule=recurrence_rule,
            series_id=series_id,
            status="pending",
        )
        self._next_id += 1
        self.items.append(created)
        self.created_pre.append(created)
        return created

    def pending_pre(self) -> list[FakeReminder]:
        return [item for item in self.items if item.status == "pending" and is_internal_pre_reminder(item.text)]


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
    repo = InMemoryRepo([FakeReminder(id=1, chat_id=42, text="buy milk", run_at=datetime(2026, 2, 22, 10, 40, tzinfo=timezone.utc))])
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
    repo = InMemoryRepo(
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
async def test_recurring_dispatch_reschedules_not_mark_done() -> None:
    item = FakeReminder(
        id=5,
        chat_id=7,
        text="daily",
        run_at=datetime(2026, 2, 22, 10, 40, tzinfo=timezone.utc),
        recurrence_rule="FREQ=DAILY",
    )
    repo = InMemoryRepo([item])
    bot = FakeBot()

    sent_count = await dispatch_due_with_repository(repository=repo, bot=bot, now=item.run_at)

    assert sent_count == 1
    assert repo.done_ids == []
    assert repo.rescheduled == [(5, datetime(2026, 2, 23, 10, 40, tzinfo=timezone.utc))]


@pytest.mark.asyncio
async def test_dispatch_strips_internal_prefix_in_user_message() -> None:
    repo = InMemoryRepo(
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


@pytest.mark.asyncio
async def test_recurring_with_until_finishes_after_last_allowed_run() -> None:
    main = FakeReminder(
        id=10,
        chat_id=100,
        text="hourly",
        run_at=datetime(2026, 2, 23, 9, 0, tzinfo=timezone.utc),
        recurrence_rule="FREQ=HOURLY;UNTIL=2026-02-23T15:00:00+00:00",
    )
    repo = InMemoryRepo([main])
    bot = FakeBot()

    for hour in range(9, 16):
        now = datetime(2026, 2, 23, hour, 0, tzinfo=timezone.utc)
        await dispatch_due_with_repository(repository=repo, bot=bot, now=now)

    assert len([msg for msg in bot.sent if msg[1] == "Напоминание: hourly"]) == 7
    assert main.status == "done"
    assert main.run_at == datetime(2026, 2, 23, 15, 0, tzinfo=timezone.utc)
    assert repo.rescheduled[-1] == (10, datetime(2026, 2, 23, 15, 0, tzinfo=timezone.utc))


@pytest.mark.asyncio
async def test_pre_reminder_for_nearest_run_only() -> None:
    main = FakeReminder(
        id=11,
        chat_id=200,
        text="daily task",
        run_at=datetime(2026, 3, 10, 9, 0, tzinfo=timezone.utc),
        recurrence_rule="FREQ=DAILY",
        series_id="series-1",
    )
    repo = InMemoryRepo([main])
    bot = FakeBot()

    await dispatch_due_with_repository(repository=repo, bot=bot, now=datetime(2026, 3, 10, 9, 0, tzinfo=timezone.utc))
    assert len(repo.pending_pre()) == 1
    assert repo.pending_pre()[0].run_at == datetime(2026, 3, 11, 8, 0, tzinfo=timezone.utc)

    await dispatch_due_with_repository(repository=repo, bot=bot, now=datetime(2026, 3, 11, 8, 0, tzinfo=timezone.utc))
    assert len(repo.pending_pre()) == 0

    await dispatch_due_with_repository(repository=repo, bot=bot, now=datetime(2026, 3, 11, 9, 0, tzinfo=timezone.utc))
    assert len(repo.pending_pre()) == 1
    assert repo.pending_pre()[0].run_at == datetime(2026, 3, 12, 8, 0, tzinfo=timezone.utc)
