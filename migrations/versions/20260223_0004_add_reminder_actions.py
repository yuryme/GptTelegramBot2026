"""add reminder actions audit table

Revision ID: 20260223_0004
Revises: 20260223_0003
Create Date: 2026-02-23
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260223_0004"
down_revision: str | None = "20260223_0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "reminder_actions",
        sa.Column("action_id", sa.String(length=36), primary_key=True),
        sa.Column("chat_id", sa.BigInteger(), nullable=False),
        sa.Column("action_type", sa.String(length=32), nullable=False),
        sa.Column("target_scope", sa.String(length=16), nullable=False),
        sa.Column("source_text", sa.Text(), nullable=True),
        sa.Column("parsed_command", sa.JSON(), nullable=True),
        sa.Column("result_stats", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_reminder_actions_chat_id", "reminder_actions", ["chat_id"])


def downgrade() -> None:
    op.drop_index("ix_reminder_actions_chat_id", table_name="reminder_actions")
    op.drop_table("reminder_actions")

