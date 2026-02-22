from collections.abc import Sequence
from datetime import datetime

from sqlalchemy import delete, insert, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.internal_reminders import INTERNAL_PRE_REMINDER_PREFIX
from app.models.reminder import Reminder, ReminderStatus


class ReminderRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def create_many(self, items: Sequence[dict]) -> list[Reminder]:
        stmt = insert(Reminder).returning(Reminder)
        result = await self._session.execute(stmt, list(items))
        await self._session.commit()
        return list(result.scalars().all())

    async def create_one(
        self,
        chat_id: int,
        text: str,
        run_at,
        recurrence_rule: str | None = None,
        status: ReminderStatus = ReminderStatus.pending,
    ) -> Reminder:
        created = await self.create_many(
            [
                {
                    "chat_id": chat_id,
                    "text": text,
                    "run_at": run_at,
                    "recurrence_rule": recurrence_rule,
                    "status": status,
                }
            ]
        )
        return created[0]

    async def list_items(
        self,
        chat_id: int,
        *,
        status: str | None = None,
        search_text: str | None = None,
        from_dt: datetime | None = None,
        to_dt: datetime | None = None,
    ) -> list[Reminder]:
        stmt = select(Reminder).where(
            Reminder.chat_id == chat_id,
            ~Reminder.text.startswith(INTERNAL_PRE_REMINDER_PREFIX),
        )

        if status:
            stmt = stmt.where(Reminder.status == ReminderStatus(status))
        if search_text:
            stmt = stmt.where(Reminder.text.ilike(f"%{search_text}%"))
        if from_dt:
            stmt = stmt.where(Reminder.run_at >= from_dt)
        if to_dt:
            stmt = stmt.where(Reminder.run_at <= to_dt)

        stmt = stmt.order_by(Reminder.run_at.asc(), Reminder.id.asc())
        result = await self._session.execute(stmt)
        return list(result.scalars().all())

    async def list_last_n(
        self,
        chat_id: int,
        n: int,
        *,
        status: str | None = None,
        search_text: str | None = None,
        from_dt: datetime | None = None,
        to_dt: datetime | None = None,
    ) -> list[Reminder]:
        stmt = select(Reminder).where(
            Reminder.chat_id == chat_id,
            ~Reminder.text.startswith(INTERNAL_PRE_REMINDER_PREFIX),
        )

        if status:
            stmt = stmt.where(Reminder.status == ReminderStatus(status))
        if search_text:
            stmt = stmt.where(Reminder.text.ilike(f"%{search_text}%"))
        if from_dt:
            stmt = stmt.where(Reminder.run_at >= from_dt)
        if to_dt:
            stmt = stmt.where(Reminder.run_at <= to_dt)

        stmt = stmt.order_by(Reminder.run_at.desc(), Reminder.id.desc()).limit(n)
        result = await self._session.execute(stmt)
        return list(result.scalars().all())

    async def delete_by_ids(self, reminder_ids: list[int]) -> int:
        if not reminder_ids:
            return 0
        stmt = delete(Reminder).where(Reminder.id.in_(reminder_ids))
        result = await self._session.execute(stmt)
        await self._session.commit()
        return result.rowcount or 0

    async def list_due_pending(self, until_dt: datetime, limit: int = 100) -> list[Reminder]:
        stmt = (
            select(Reminder)
            .where(Reminder.status == ReminderStatus.pending, Reminder.run_at <= until_dt)
            .order_by(Reminder.run_at.asc(), Reminder.id.asc())
            .limit(limit)
        )
        result = await self._session.execute(stmt)
        return list(result.scalars().all())

    async def mark_done(self, reminder_ids: list[int]) -> int:
        if not reminder_ids:
            return 0
        stmt = (
            update(Reminder)
            .where(Reminder.id.in_(reminder_ids))
            .values(status=ReminderStatus.done)
        )
        result = await self._session.execute(stmt)
        await self._session.commit()
        return result.rowcount or 0

    async def reschedule(self, reminder_id: int, next_run_at: datetime) -> int:
        stmt = (
            update(Reminder)
            .where(Reminder.id == reminder_id)
            .values(run_at=next_run_at, status=ReminderStatus.pending)
        )
        result = await self._session.execute(stmt)
        await self._session.commit()
        return result.rowcount or 0
