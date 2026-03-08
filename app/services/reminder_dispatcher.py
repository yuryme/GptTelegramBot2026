from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Protocol

from aiogram import Bot

from app.core.internal_reminders import (
    build_pre_reminder_text,
    is_internal_pre_reminder,
    should_create_pre_reminder,
    unwrap_internal_text,
)
from app.core.settings import get_settings
from app.db.session import SessionLocal
from app.repositories.reminder_repository import ReminderRepository
from app.services.recurrence import compute_next_run_at
from zoneinfo import ZoneInfo

logger = logging.getLogger(__name__)


class DueReminderRepository(Protocol):
    async def list_due_pending(self, until_dt: datetime, limit: int = 100): ...

    async def mark_done(self, reminder_ids: list[int]) -> int: ...

    async def reschedule(self, reminder_id: int, next_run_at: datetime) -> int: ...

    async def create_one(
        self,
        chat_id: int,
        text: str,
        run_at: datetime,
        recurrence_rule: str | None = None,
        series_id: str | None = None,
    ): ...


async def dispatch_due_with_repository(
    *,
    repository: DueReminderRepository,
    bot: Bot,
    now: datetime | None = None,
    batch_size: int = 100,
) -> int:
    now = now or datetime.now(timezone.utc)
    settings = get_settings()
    now_local = now.astimezone(ZoneInfo(settings.app_timezone))
    due_items = await repository.list_due_pending(until_dt=now, limit=batch_size)
    if not due_items:
        return 0

    sent_once_ids: list[int] = []
    rescheduled_count = 0
    for item in due_items:
        try:
            is_pre_reminder = is_internal_pre_reminder(item.text)
            await bot.send_message(chat_id=item.chat_id, text=f"Напоминание: {unwrap_internal_text(item.text)}")
            next_run_at = compute_next_run_at(item.run_at, getattr(item, "recurrence_rule", None))
            if next_run_at is None:
                sent_once_ids.append(item.id)
            else:
                await repository.reschedule(item.id, next_run_at)
                if not is_pre_reminder and should_create_pre_reminder(run_at_utc=next_run_at, now_local=now_local):
                    await repository.create_one(
                        chat_id=item.chat_id,
                        text=build_pre_reminder_text(unwrap_internal_text(item.text)),
                        run_at=next_run_at - timedelta(hours=1),
                        recurrence_rule=None,
                        series_id=getattr(item, "series_id", None),
                    )
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
