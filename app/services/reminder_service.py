from dataclasses import dataclass
from datetime import datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo

from app.core.internal_reminders import build_pre_reminder_text, is_internal_pre_reminder, unwrap_internal_text
from app.core.settings import get_settings
from app.models.reminder import ReminderStatus
from app.repositories.reminder_repository import ReminderRepository
from app.schemas.commands import (
    CreateRemindersCommand,
    DeleteRemindersCommand,
    ListRemindersCommand,
    resolve_default_run_at,
)


@dataclass(slots=True)
class CreatedReminderResult:
    id: int
    text: str
    run_at: datetime
    recurrence_rule: str | None


@dataclass(slots=True)
class ReminderListItem:
    id: int
    text: str
    run_at: datetime
    status: str
    recurrence_rule: str | None


@dataclass(slots=True)
class DeletedReminderResult:
    deleted_count: int
    items: list[ReminderListItem]


class ReminderService:
    def __init__(self, repository: ReminderRepository) -> None:
        self._repository = repository

    async def create_from_command(
        self,
        chat_id: int,
        command: CreateRemindersCommand,
        now: datetime | None = None,
    ) -> list[CreatedReminderResult]:
        settings = get_settings()
        local_tz = ZoneInfo(settings.app_timezone)
        now = now or datetime.now(local_tz)
        payload = []
        for reminder in command.reminders:
            run_at = resolve_default_run_at(reminder, now)
            run_at_local = run_at.replace(tzinfo=local_tz) if run_at.tzinfo is None else run_at
            run_at_utc = run_at_local.astimezone(timezone.utc)
            tomorrow_date = (now + timedelta(days=1)).date()

            if run_at_local.date() >= tomorrow_date:
                payload.append(
                    {
                        "chat_id": chat_id,
                        "text": build_pre_reminder_text(reminder.text),
                        "run_at": run_at_utc - timedelta(hours=1),
                        "recurrence_rule": reminder.recurrence_rule,
                    }
                )

            payload.append(
                {
                    "chat_id": chat_id,
                    "text": reminder.text,
                    "run_at": run_at_utc,
                    "recurrence_rule": reminder.recurrence_rule,
                }
            )

        created = await self._repository.create_many(payload)
        return [
            CreatedReminderResult(
                id=item.id,
                text=unwrap_internal_text(item.text),
                run_at=item.run_at,
                recurrence_rule=item.recurrence_rule,
            )
            for item in created
            if not is_internal_pre_reminder(item.text)
        ]

    async def list_from_command(
        self,
        chat_id: int,
        command: ListRemindersCommand,
        now: datetime | None = None,
    ) -> list[ReminderListItem]:
        settings = get_settings()
        local_tz = ZoneInfo(settings.app_timezone)
        now = now or datetime.now(local_tz)
        status = command.status
        search_text = command.search_text
        from_dt = command.from_dt
        to_dt = command.to_dt

        if command.mode == "today":
            day_start = datetime.combine(now.date(), time.min, tzinfo=now.tzinfo or timezone.utc)
            day_end = day_start + timedelta(days=1) - timedelta(microseconds=1)
            from_dt = day_start
            to_dt = day_end

        records = await self._repository.list_items(
            chat_id,
            status=status,
            search_text=search_text,
            from_dt=from_dt,
            to_dt=to_dt,
        )
        return [
            ReminderListItem(
                id=item.id,
                text=item.text,
                run_at=item.run_at,
                status=item.status.value if isinstance(item.status, ReminderStatus) else str(item.status),
                recurrence_rule=item.recurrence_rule,
            )
            for item in records
        ]

    async def delete_from_command(
        self,
        chat_id: int,
        command: DeleteRemindersCommand,
    ) -> DeletedReminderResult:
        if command.mode == "last_n":
            selected = await self._repository.list_last_n(
                chat_id=chat_id,
                n=command.last_n or 0,
                status=command.status,
                search_text=command.search_text,
                from_dt=command.from_dt,
                to_dt=command.to_dt,
            )
        else:
            selected = await self._repository.list_items(
                chat_id=chat_id,
                status=command.status,
                search_text=command.search_text,
                from_dt=command.from_dt,
                to_dt=command.to_dt,
            )

        selected_items = [
            ReminderListItem(
                id=item.id,
                text=item.text,
                run_at=item.run_at,
                status=item.status.value if isinstance(item.status, ReminderStatus) else str(item.status),
                recurrence_rule=item.recurrence_rule,
            )
            for item in selected
        ]
        deleted_count = await self._repository.delete_by_ids([item.id for item in selected_items])
        return DeletedReminderResult(deleted_count=deleted_count, items=selected_items)
