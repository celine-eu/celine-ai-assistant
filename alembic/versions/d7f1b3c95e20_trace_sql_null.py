"""messages.trace: the JSON value `null` becomes SQL NULL (REQ-0053).

v1.7.0 stored `user` messages' missing trace as the JSON value `null`; rows from before
the column, and every row from now on, hold SQL NULL. Data only, no schema change.

Revision ID: d7f1b3c95e20
Revises: c4e8a2d61b07
Create Date: 2026-10-26 19:00:00.000000
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "d7f1b3c95e20"
down_revision: str | None = "c4e8a2d61b07"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        sa.text("UPDATE messages SET trace = NULL WHERE CAST(trace AS TEXT) = 'null'")
    )


def downgrade() -> None:
    # Nothing to restore: SQL NULL and JSON null mean the same "no trace".
    pass
