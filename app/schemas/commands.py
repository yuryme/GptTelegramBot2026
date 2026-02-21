from __future__ import annotations

from datetime import date, datetime, time, timedelta, timezone
from enum import Enum
from typing import Annotated, Literal

from pydantic import BaseModel, Field, TypeAdapter, model_validator


class CommandName(str, Enum):
    create = "create_reminders"
    list_items = "list_reminders"
    delete = "delete_reminders"


class DayReference(str, Enum):
    today = "today"
    tomorrow = "tomorrow"
    day_after_tomorrow = "day_after_tomorrow"
    weekday = "weekday"
    specific_date = "specific_date"


class ReminderInput(BaseModel):
    text: str = Field(min_length=1, max_length=1000)
    run_at: datetime | None = None
    recurrence_rule: str | None = Field(default=None, max_length=255)
    day_reference: DayReference | None = None
    weekday: int | None = Field(default=None, ge=0, le=6)
    date_value: date | None = None
    explicit_time_provided: bool = False

    @model_validator(mode="after")
    def validate_time_or_day(self) -> "ReminderInput":
        if self.run_at is None and self.day_reference is None:
            raise ValueError("Either run_at or day_reference must be provided")

        if self.day_reference != DayReference.weekday and self.weekday is not None:
            raise ValueError("weekday is only allowed when day_reference=weekday")

        if self.day_reference != DayReference.specific_date and self.date_value is not None:
            raise ValueError("date_value is only allowed when day_reference=specific_date")

        if self.day_reference == DayReference.weekday and self.weekday is None:
            raise ValueError("weekday is required when day_reference=weekday")

        if self.day_reference == DayReference.specific_date and self.date_value is None:
            raise ValueError("date_value is required when day_reference=specific_date")

        return self


class CreateRemindersCommand(BaseModel):
    command: Literal[CommandName.create]
    reminders: list[ReminderInput] = Field(min_length=1, max_length=30)


class ListRemindersCommand(BaseModel):
    command: Literal[CommandName.list_items]
    mode: Literal["all", "today", "status", "search", "range"] = "all"
    status: Literal["pending", "done", "canceled"] | None = None
    search_text: str | None = None
    from_dt: datetime | None = None
    to_dt: datetime | None = None


class DeleteRemindersCommand(BaseModel):
    command: Literal[CommandName.delete]
    mode: Literal["filter", "last_n"] = "filter"
    last_n: int | None = Field(default=None, ge=1, le=100)
    status: Literal["pending", "done", "canceled"] | None = None
    search_text: str | None = None
    from_dt: datetime | None = None
    to_dt: datetime | None = None

    @model_validator(mode="after")
    def validate_delete_mode(self) -> "DeleteRemindersCommand":
        if self.mode == "last_n" and self.last_n is None:
            raise ValueError("last_n is required when mode=last_n")
        return self


AssistantCommand = Annotated[
    CreateRemindersCommand | ListRemindersCommand | DeleteRemindersCommand,
    Field(discriminator="command"),
]

assistant_command_adapter = TypeAdapter(AssistantCommand)


def next_weekday(base_dt: datetime, weekday: int) -> datetime:
    days_ahead = (weekday - base_dt.weekday()) % 7
    if days_ahead == 0:
        days_ahead = 7
    return base_dt + timedelta(days=days_ahead)


def resolve_default_run_at(reminder: ReminderInput, now: datetime) -> datetime:
    if reminder.run_at is not None:
        return reminder.run_at if reminder.run_at.tzinfo else reminder.run_at.replace(tzinfo=timezone.utc)

    if reminder.day_reference is None:
        raise ValueError("day_reference must be provided when run_at is missing")

    if reminder.day_reference == DayReference.today:
        rounded = now.replace(minute=0, second=0, microsecond=0)
        if now > rounded:
            rounded += timedelta(hours=1)
        return rounded

    if reminder.day_reference == DayReference.tomorrow:
        day_date = (now + timedelta(days=1)).date()
    elif reminder.day_reference == DayReference.day_after_tomorrow:
        day_date = (now + timedelta(days=2)).date()
    elif reminder.day_reference == DayReference.weekday:
        day_date = next_weekday(now, reminder.weekday or 0).date()
    elif reminder.day_reference == DayReference.specific_date:
        day_date = reminder.date_value or now.date()
        if day_date <= now.date():
            raise ValueError("specific_date must be in the future when time is omitted")
    else:
        raise ValueError("Unsupported day_reference")

    return datetime.combine(day_date, time(hour=8, minute=0), tzinfo=now.tzinfo or timezone.utc)
