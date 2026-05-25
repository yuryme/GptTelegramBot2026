from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field, TypeAdapter


class ScheduleDraft(BaseModel):
    kind: Literal["once", "recurring"]
    start_at: datetime
    end_at: datetime | None = None
    frequency: Literal["minutely", "hourly", "daily", "weekly", "monthly"] | None = None
    interval: int | None = Field(default=None, ge=1, le=365)
    weekdays: list[int] | None = None
    month_day: int | None = Field(default=None, ge=1, le=31)


class CreateReminderDraft(BaseModel):
    reminder_text: str = Field(min_length=1, max_length=1000)
    schedule: ScheduleDraft | None = None
    day_expression: str | None = None
    time_expression: str | None = None
    date_expression: str | None = None
    period_start_expression: str | None = None
    period_end_expression: str | None = None
    recurrence_expression: str | None = None
    recurrence_until_expression: str | None = None
    recurrence_interval: int | None = Field(default=None, ge=1, le=365)
    pre_reminder_expression: str | None = None
    raw_context: str | None = None


class SemanticCommandDraft(BaseModel):
    intent: Literal["create_reminders", "list_reminders", "delete_reminders"]
    create_items: list[CreateReminderDraft] = Field(default_factory=list)
    passthrough_command: dict[str, Any] | None = None


semantic_command_draft_adapter = TypeAdapter(SemanticCommandDraft)
