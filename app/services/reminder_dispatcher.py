from __future__ import annotations

import logging
from calendar import monthrange
from datetime import datetime, timezone
from typing import Protocol

from aiogram import Bot

from app.core.internal_reminders import unwrap_internal_text
from app.db.session import SessionLocal
from app.repositories.reminder_repository import ReminderRepository

logger = logging.getLogger(__name__)


class DueReminderRepository(Protocol):
    async def list_due_pending(self, until_dt: datetime, limit: int = 100): ...

    async def mark_done(self, reminder_ids: list[int]) -> int: ...

    async def reschedule(self, reminder_id: int, next_run_at: datetime) -> int: ...


def _add_months(base_dt: datetime, months: int) -> datetime:
    y = base_dt.year
    m = base_dt.month + months
    y += (m - 1) // 12
    m = (m - 1) % 12 + 1
    max_day = monthrange(y, m)[1]
    d = min(base_dt.day, max_day)
    return base_dt.replace(year=y, month=m, day=d)


def compute_next_run_at(current_run_at: datetime, recurrence_rule: str | None) -> datetime | None:
    if not recurrence_rule:
        return None
    parts: dict[str, str] = {}
    for token in recurrence_rule.split(";"):
        if "=" not in token:
            continue
        k, v = token.split("=", 1)
        parts[k.strip().upper()] = v.strip().upper()

    freq = parts.get("FREQ")
    if not freq:
        return None
    try:
        interval = max(1, int(parts.get("INTERVAL", "1")))
    except ValueError:
        interval = 1

    if freq == "DAILY":
        from datetime import timedelta

        return current_run_at + timedelta(days=interval)
    if freq == "WEEKLY":
        from datetime import timedelta

        return current_run_at + timedelta(weeks=interval)
    if freq == "MONTHLY":
        return _add_months(current_run_at, interval)
    return None


async def dispatch_due_with_repository(
    *,
    repository: DueReminderRepository,
    bot: Bot,
    now: datetime | None = None,
    batch_size: int = 100,
) -> int:
    now = now or datetime.now(timezone.utc)
    due_items = await repository.list_due_pending(until_dt=now, limit=batch_size)
    if not due_items:
        return 0

    sent_once_ids: list[int] = []
    rescheduled_count = 0
    for item in due_items:
        try:
            await bot.send_message(chat_id=item.chat_id, text=f"Напоминание: {unwrap_internal_text(item.text)}")
            next_run_at = compute_next_run_at(item.run_at, getattr(item, "recurrence_rule", None))
            if next_run_at is None:
                sent_once_ids.append(item.id)
            else:
                await repository.reschedule(item.id, next_run_at)
                rescheduled_count += 1
        except Exception:
            logger.exception("Failed to send reminder id=%s chat_id=%s", item.id, item.chat_id)

    if sent_once_ids:
        await repository.mark_done(sent_once_ids)
    return len(sent_once_ids) + rescheduled_count


async def dispatch_due_reminders(bot: Bot, now: datetime | None = None, batch_size: int = 100) -> int:
    async with SessionLocal() as session:
        repository = ReminderRepository(session)
        sent_count = await dispatch_due_with_repository(
            repository=repository,
            bot=bot,
            now=now,
            batch_size=batch_size,
        )
        if sent_count:
            logger.info("Due reminders dispatched: count=%s", sent_count)
        return sent_count
