from dataclasses import dataclass
from datetime import datetime, time, timedelta, timezone
from uuid import uuid4
from zoneinfo import ZoneInfo

from app.core.internal_reminders import (
    build_pre_reminder_text,
    is_internal_pre_reminder,
    should_create_pre_reminder,
    unwrap_internal_text,
)
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


@dataclass(slots=True)
class SelectionFilter:
    by_id: int | None = None
    by_status: str | None = None
    by_text_contains: str | None = None
    by_due_from: datetime | None = None
    by_due_to: datetime | None = None
    include_deleted: bool = False


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
            series_id: str | None = None
            if reminder.recurrence_rule:
                series_id = str(uuid4())
                await self._repository.create_series(
                    series_id=series_id,
                    chat_id=chat_id,
                    source_text=reminder.text,
                    recurrence_rule=reminder.recurrence_rule,
                )
            if should_create_pre_reminder(run_at_utc=run_at_utc, now_local=now):
                payload.append(
                    {
                        "chat_id": chat_id,
                        "text": build_pre_reminder_text(reminder.text),
                        "run_at": run_at_utc - timedelta(hours=1),
                        "recurrence_rule": None,
                        "series_id": series_id,
                    }
                )

            payload.append(
                {
                    "chat_id": chat_id,
                    "text": reminder.text,
                    "run_at": run_at_utc,
                    "recurrence_rule": reminder.recurrence_rule,
                    "series_id": series_id,
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
        selection = self._selection_from_list_command(command=command, now=now)
        records = await self._select_items(chat_id=chat_id, selection=selection)
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
        # Fail-safe: never delete all reminders implicitly.
        if (
            command.mode == "filter"
            and not command.confirm_delete_all
            and command.reminder_id is None
            and command.status is None
            and command.search_text is None
            and command.from_dt is None
            and command.to_dt is None
        ):
            return DeletedReminderResult(deleted_count=0, items=[])

        selection = SelectionFilter(
            by_id=command.reminder_id,
            by_status=command.status,
            by_text_contains=command.search_text,
            by_due_from=command.from_dt,
            by_due_to=command.to_dt,
        )
        selected = await self._select_items(
            chat_id=chat_id,
            selection=selection,
            last_n=command.last_n if command.mode == "last_n" else None,
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

    async def _select_items(
        self,
        *,
        chat_id: int,
        selection: SelectionFilter,
        last_n: int | None = None,
    ):
        if last_n is not None:
            return await self._repository.list_last_n(
                chat_id=chat_id,
                n=last_n,
                reminder_id=selection.by_id,
                status=selection.by_status,
                search_text=selection.by_text_contains,
                from_dt=selection.by_due_from,
                to_dt=selection.by_due_to,
                include_deleted=selection.include_deleted,
            )
        return await self._repository.list_items(
            chat_id=chat_id,
            reminder_id=selection.by_id,
            status=selection.by_status,
            search_text=selection.by_text_contains,
            from_dt=selection.by_due_from,
            to_dt=selection.by_due_to,
            include_deleted=selection.include_deleted,
        )

    def _selection_from_list_command(self, *, command: ListRemindersCommand, now: datetime) -> SelectionFilter:
        selection = SelectionFilter(
            by_status=command.status,
            by_text_contains=command.search_text,
            by_due_from=command.from_dt,
            by_due_to=command.to_dt,
        )
        if command.mode == "today":
            day_start = datetime.combine(now.date(), time.min, tzinfo=now.tzinfo or timezone.utc)
            day_end = day_start + timedelta(days=1) - timedelta(microseconds=1)
            selection.by_due_from = day_start
            selection.by_due_to = day_end
        if command.status == "deleted":
            selection.include_deleted = True
        return selection
