"""Knowledge bases per community: attachments.community_id, kb_sources.

Revision ID: a1c3e5f70912
Revises: 6fb1b67e3843
Create Date: 2026-10-02 12:00:00.000000
"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "a1c3e5f70912"
down_revision: Union[str, None] = "6fb1b67e3843"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "attachments", sa.Column("community_id", sa.String(length=64), nullable=True)
    )
    op.create_index("idx_att_community", "attachments", ["community_id"], unique=False)

    op.create_table(
        "kb_sources",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("community_id", sa.String(length=64), nullable=False),
        sa.Column("kind", sa.String(length=8), nullable=False),
        sa.Column("location", sa.Text(), nullable=False),
        sa.Column("ref", sa.String(length=256), nullable=True),
        sa.Column("subpath", sa.Text(), nullable=True),
        sa.Column("last_synced_version", sa.String(length=64), nullable=True),
        sa.Column("last_synced_at", sa.BigInteger(), nullable=True),
        sa.Column("created_at", sa.BigInteger(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("idx_kbsrc_community", "kb_sources", ["community_id"], unique=False)

    op.create_table(
        "kb_source_documents",
        sa.Column("source_id", sa.String(length=36), nullable=False),
        sa.Column("collection", sa.String(length=255), nullable=False),
        sa.Column("path", sa.String(length=1024), nullable=False),
        sa.Column("version", sa.String(length=64), nullable=False),
        sa.ForeignKeyConstraint(["source_id"], ["kb_sources.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("source_id", "collection", "path"),
    )


def downgrade() -> None:
    op.drop_table("kb_source_documents")
    op.drop_index("idx_kbsrc_community", table_name="kb_sources")
    op.drop_table("kb_sources")
    op.drop_index("idx_att_community", table_name="attachments")
    op.drop_column("attachments", "community_id")
