"""add publication table (BCRD publications + AI digests)

Stores ingested editions of recurring BCRD reports (Estabilidad Financiera,
Economía Dominicana, IPOM) with the extracted text and the structured AI digest.
JSON columns are portable across SQLite (dev) and PostgreSQL (prod).

Revision ID: e7f1a2b3c4d5
Revises: f1a2b3c4d5e6
Create Date: 2026-06-12
"""
import sqlalchemy as sa
from alembic import op

revision = "e7f1a2b3c4d5"
down_revision = "f1a2b3c4d5e6"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "publication",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.Column("report_key", sa.String(length=60), nullable=False),
        sa.Column("report_name", sa.String(length=200), nullable=False, server_default=""),
        sa.Column("period", sa.String(length=60), nullable=False),
        sa.Column("title", sa.String(length=300), nullable=False, server_default=""),
        sa.Column("source_url", sa.String(length=600), nullable=False, server_default=""),
        sa.Column("landing_url", sa.String(length=600), nullable=False, server_default=""),
        sa.Column("published_at", sa.String(length=40), nullable=True),
        sa.Column("sectors", sa.JSON(), nullable=True),
        sa.Column("raw_text", sa.Text(), nullable=True),
        sa.Column("digest", sa.JSON(), nullable=True),
        sa.Column("status", sa.String(length=20), nullable=False, server_default="pending"),
        sa.Column("error", sa.Text(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("report_key", "period", name="uq_publication_report_period"),
    )
    op.create_index("ix_publication_report_key", "publication", ["report_key"])
    op.create_index("ix_publication_period", "publication", ["period"])


def downgrade() -> None:
    op.drop_index("ix_publication_period", table_name="publication")
    op.drop_index("ix_publication_report_key", table_name="publication")
    op.drop_table("publication")
