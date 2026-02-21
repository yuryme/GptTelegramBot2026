"""init reminders

Revision ID: 20260221_0001
Revises:
Create Date: 2026-02-21
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260221_0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    status_enum = sa.Enum("pending", "done", "canceled", name="reminder_status")

    op.create_table(
        "reminders",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("chat_id", sa.BigInteger(), nullable=False),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("run_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("status", status_enum, nullable=False, server_default="pending"),
        sa.Column("recurrence_rule", sa.String(length=255), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_reminders_chat_id", "reminders", ["chat_id"])
    op.create_index("ix_reminders_run_at", "reminders", ["run_at"])


def downgrade() -> None:
    op.drop_index("ix_reminders_run_at", table_name="reminders")
    op.drop_index("ix_reminders_chat_id", table_name="reminders")
    op.drop_table("reminders")
    sa.Enum("pending", "done", "canceled", name="reminder_status").drop(op.get_bind(), checkfirst=True)
