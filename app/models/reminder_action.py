from datetime import datetime

from sqlalchemy import BigInteger, DateTime, JSON, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class ReminderAction(Base):
    __tablename__ = "reminder_actions"

    action_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    chat_id: Mapped[int] = mapped_column(BigInteger, nullable=False, index=True)
    action_type: Mapped[str] = mapped_column(String(32), nullable=False)
    target_scope: Mapped[str] = mapped_column(String(16), nullable=False)
    source_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    parsed_command: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    result_stats: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow, nullable=False)
