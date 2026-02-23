"""add deleted status to reminder_status enum

Revision ID: 20260223_0002
Revises: 20260221_0001
Create Date: 2026-02-23
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260223_0002"
down_revision: str | None = "20260221_0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        op.execute("ALTER TYPE reminder_status ADD VALUE IF NOT EXISTS 'deleted';")


def downgrade() -> None:
    # PostgreSQL does not support dropping enum values safely in-place.
    # Leave enum as-is on downgrade.
    pass
