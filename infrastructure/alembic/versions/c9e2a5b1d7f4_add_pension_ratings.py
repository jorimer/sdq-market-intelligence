"""add pension_ratings table (Índice de Solidez de AFP)

Revision ID: c9e2a5b1d7f4
Revises: b8d1f4a2c6e9
Create Date: 2026-06-27

Persists the computed ISA (band index, not a credit rating) per AFP/period. Written
by hand from modules/pension_intel/models/models.py. See tasks/PLAN_PENSIONES_SIPEN.md (F2).
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "c9e2a5b1d7f4"
down_revision: Union[str, None] = "b8d1f4a2c6e9"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "pension_ratings",
        sa.Column("entity_slug", sa.String(length=40), nullable=False),
        sa.Column("period", sa.String(length=10), nullable=False),
        sa.Column("overall_score", sa.Float(), nullable=True),
        sa.Column("band", sa.String(length=20), nullable=True),
        sa.Column("coverage", sa.Float(), nullable=True),
        sa.Column("dimensions", sa.JSON(), nullable=True),
        sa.Column("model_version", sa.String(length=10), nullable=False),
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("created_at", sa.DateTime(),
                  server_default=sa.text("(CURRENT_TIMESTAMP)"), nullable=False),
        sa.Column("updated_at", sa.DateTime(),
                  server_default=sa.text("(CURRENT_TIMESTAMP)"), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("entity_slug", "period", name="uq_pension_rating_entity_period"),
    )
    op.create_index("ix_pension_rating_entity_period", "pension_ratings",
                    ["entity_slug", "period"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_pension_rating_entity_period", table_name="pension_ratings")
    op.drop_table("pension_ratings")
