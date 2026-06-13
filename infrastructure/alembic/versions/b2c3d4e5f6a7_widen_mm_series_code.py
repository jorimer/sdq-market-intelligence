"""widen mm_series.series_code 60 -> 255 (BCRD Excel engine codes)

The AI-native Excel engine emits hierarchical series codes
("bcrd.xls.<file>.<metric>", up to ~95 chars) that overflow the original
VARCHAR(60). PostgreSQL ENFORCES the length and rejected the whole insert
(StringDataRightTruncation -> 502); SQLite does not, so dev/tests passed. Widen
to 255 so the canonical/long-coded series persist in prod.

SQLite is a no-op: it ignores declared VARCHAR length, and ``alter_column`` type
changes there require table-rebuild (batch) — pointless when nothing is enforced.

Revision ID: b2c3d4e5f6a7
Revises: a1b2c3d4e5f6
Create Date: 2026-06-13
"""
import sqlalchemy as sa
from alembic import op

revision = "b2c3d4e5f6a7"
down_revision = "a1b2c3d4e5f6"
branch_labels = None
depends_on = None


def upgrade() -> None:
    if op.get_bind().dialect.name == "sqlite":
        return  # SQLite ignores VARCHAR length; nothing to enforce or alter.
    op.alter_column(
        "mm_series", "series_code",
        existing_type=sa.String(length=60),
        type_=sa.String(length=255),
        existing_nullable=False,
    )


def downgrade() -> None:
    if op.get_bind().dialect.name == "sqlite":
        return
    # Note: reverting to 60 will fail if any persisted code exceeds 60 chars.
    op.alter_column(
        "mm_series", "series_code",
        existing_type=sa.String(length=255),
        type_=sa.String(length=60),
        existing_nullable=False,
    )
