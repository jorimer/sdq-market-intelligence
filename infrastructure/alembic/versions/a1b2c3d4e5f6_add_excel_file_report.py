"""add mm_excel_reports table (BCRD Excel ingestion coverage)

One row per source Excel file (latest run of the AI-native engine over the BCRD
historical corpus): how it resolved (method/orientation/confidence), how many
series/observations it yielded, what's flagged for review or failed. JSON column
is portable across SQLite (dev) and PostgreSQL (prod).

Revision ID: a1b2c3d4e5f6
Revises: e7f1a2b3c4d5
Create Date: 2026-06-13
"""
import sqlalchemy as sa
from alembic import op

revision = "a1b2c3d4e5f6"
down_revision = "e7f1a2b3c4d5"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "mm_excel_reports",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.Column("file_url", sa.String(length=500), nullable=False),
        sa.Column("filename", sa.String(length=200), nullable=True),
        sa.Column("sector", sa.String(length=60), nullable=True),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("method", sa.String(length=20), nullable=True),
        sa.Column("orientation", sa.String(length=20), nullable=True),
        sa.Column("frequency", sa.String(length=20), nullable=True),
        sa.Column("confidence", sa.Float(), nullable=True),
        sa.Column("n_records", sa.Float(), nullable=True),
        sa.Column("n_series", sa.Float(), nullable=True),
        sa.Column("n_flagged", sa.Float(), nullable=True),
        sa.Column("persisted", sa.Float(), nullable=True),
        sa.Column("error", sa.String(length=500), nullable=True),
        sa.Column("flags", sa.JSON(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("file_url", name="uq_mm_excel_file"),
    )
    op.create_index("ix_mm_excel_status", "mm_excel_reports", ["status"])


def downgrade() -> None:
    op.drop_index("ix_mm_excel_status", table_name="mm_excel_reports")
    op.drop_table("mm_excel_reports")
