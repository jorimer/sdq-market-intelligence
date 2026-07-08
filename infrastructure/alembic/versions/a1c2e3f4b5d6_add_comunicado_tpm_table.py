"""add comunicado_tpm table (BCRD monetary-policy communiqués + AI digest)

Stores each BCRD monetary-policy decision (Comunicados de Política Monetaria) with the
deterministically-parsed decision (action + resulting TPM level) and the AI digest of
the rationale. Distinct from ``publication`` (PDF reports): these are HTML articles from
the BCRD press room, a stream (one per Junta Monetaria meeting). JSON is portable across
SQLite (dev) and PostgreSQL (prod).

Revision ID: a1c2e3f4b5d6
Revises: f4a9c1e6b830
Create Date: 2026-07-08
"""
import sqlalchemy as sa
from alembic import op

revision = "a1c2e3f4b5d6"
down_revision = "f4a9c1e6b830"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "comunicado_tpm",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.Column("article_id", sa.Integer(), nullable=False),
        sa.Column("string_id", sa.String(length=200), nullable=False, server_default=""),
        sa.Column("title", sa.String(length=300), nullable=False, server_default=""),
        sa.Column("decision_date", sa.String(length=10), nullable=True),
        sa.Column("action", sa.String(length=10), nullable=True),
        sa.Column("tpm_level", sa.Float(), nullable=True),
        sa.Column("bps_change", sa.Integer(), nullable=True),
        sa.Column("source_url", sa.String(length=600), nullable=False, server_default=""),
        sa.Column("body_text", sa.Text(), nullable=True),
        sa.Column("digest", sa.JSON(), nullable=True),
        sa.Column("status", sa.String(length=20), nullable=False, server_default="pending"),
        sa.Column("error", sa.Text(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("article_id", name="uq_comunicado_tpm_article"),
    )
    op.create_index("ix_comunicado_tpm_article_id", "comunicado_tpm", ["article_id"])
    op.create_index("ix_comunicado_tpm_decision_date", "comunicado_tpm", ["decision_date"])


def downgrade() -> None:
    op.drop_index("ix_comunicado_tpm_decision_date", table_name="comunicado_tpm")
    op.drop_index("ix_comunicado_tpm_article_id", table_name="comunicado_tpm")
    op.drop_table("comunicado_tpm")
