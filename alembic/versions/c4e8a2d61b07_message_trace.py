"""What produced an answer: messages.trace (REQ-0053).

Nullable, no backfill: `user` messages and answers stored before this have no trace.

Revision ID: c4e8a2d61b07
Revises: a1c3e5f70912
Create Date: 2026-10-26 12:00:00.000000
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "c4e8a2d61b07"
down_revision: str | None = "a1c3e5f70912"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("messages", sa.Column("trace", sa.JSON(), nullable=True))


def downgrade() -> None:
    op.drop_column("messages", "trace")
