from datetime import datetime
from enum import Enum

from sqlalchemy import DateTime, Enum as SqlEnum, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class ReminderStatus(str, Enum):
    pending = "pending"
    done = "done"
    deleted = "deleted"
    canceled = "canceled"  # legacy value kept for backward compatibility


class Reminder(Base):
    __tablename__ = "reminders"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    chat_id: Mapped[int] = mapped_column(index=True)
    text: Mapped[str] = mapped_column(Text, nullable=False)
    run_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    status: Mapped[ReminderStatus] = mapped_column(
        SqlEnum(ReminderStatus, name="reminder_status"),
        default=ReminderStatus.pending,
        nullable=False,
    )
    recurrence_rule: Mapped[str | None] = mapped_column(String(255), nullable=True)
    series_id: Mapped[str | None] = mapped_column(String(36), nullable=True, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=datetime.utcnow, onupdate=datetime.utcnow
    )
