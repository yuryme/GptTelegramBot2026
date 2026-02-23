"""add reminder_series table and series_id link

Revision ID: 20260223_0003
Revises: 20260223_0002
Create Date: 2026-02-23
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260223_0003"
down_revision: str | None = "20260223_0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "reminder_series",
        sa.Column("series_id", sa.String(length=36), primary_key=True),
        sa.Column("chat_id", sa.BigInteger(), nullable=False),
        sa.Column("source_text", sa.Text(), nullable=False),
        sa.Column("recurrence_rule", sa.String(length=255), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_reminder_series_chat_id", "reminder_series", ["chat_id"])

    op.add_column("reminders", sa.Column("series_id", sa.String(length=36), nullable=True))
    op.create_index("ix_reminders_series_id", "reminders", ["series_id"])


def downgrade() -> None:
    op.drop_index("ix_reminders_series_id", table_name="reminders")
    op.drop_column("reminders", "series_id")

    op.drop_index("ix_reminder_series_chat_id", table_name="reminder_series")
    op.drop_table("reminder_series")

