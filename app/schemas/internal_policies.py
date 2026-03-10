from __future__ import annotations

from datetime import datetime
from enum import Enum

from pydantic import BaseModel, Field


class RecurrenceKind(str, Enum):
    one_time = "one_time"
    hourly = "hourly"
    daily = "daily"
    weekly = "weekly"
    monthly = "monthly"


class RecurrenceEndKind(str, Enum):
    never = "never"
    until_datetime = "until_datetime"


class RecurrenceEndIntent(str, Enum):
    default_until_same_day = "default_until_same_day"
    default_until_end_of_week = "default_until_end_of_week"
    default_until_end_of_month = "default_until_end_of_month"
    default_until_end_of_year = "default_until_end_of_year"
    until_date = "until_date"
    until_datetime = "until_datetime"
    until_period_end = "until_period_end"
    until_duration_from_start = "until_duration_from_start"
    ambiguous = "ambiguous"


class PreReminderMode(str, Enum):
    auto = "auto"
    disabled = "disabled"
    minutes_before = "minutes_before"


class InternalRecurrencePolicy(BaseModel):
    kind: RecurrenceKind = RecurrenceKind.one_time
    interval: int = Field(default=1, ge=1, le=365)
    weekdays: list[int] = Field(default_factory=list)
    month_day: int | None = Field(default=None, ge=1, le=31)
    end_kind: RecurrenceEndKind = RecurrenceEndKind.never
    end_intent: RecurrenceEndIntent | None = None
    until: datetime | None = None
    legacy_rule: str | None = None


class InternalDisplayPolicy(BaseModel):
    user_time: str | None = None
    pre_reminder_mode: PreReminderMode = PreReminderMode.auto
    pre_reminder_minutes: int | None = Field(default=None, ge=1, le=24 * 60)


class CompiledCreateReminderPlan(BaseModel):
    reminder_payload: dict[str, object]
    recurrence: InternalRecurrencePolicy
    display: InternalDisplayPolicy
