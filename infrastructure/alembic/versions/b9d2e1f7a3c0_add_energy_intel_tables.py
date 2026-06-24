"""add energy_intel tables (IRSE scores)

Revision ID: b9d2e1f7a3c0
Revises: e9c4a7b2f1d8
Create Date: 2026-06-24

"""
from typing import Sequence, Union

import sqlalchemy as sa

from alembic import op

revision: str = "b9d2e1f7a3c0"
down_revision: Union[str, None] = "e9c4a7b2f1d8"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "en_scores",
        sa.Column("period", sa.String(length=10), nullable=False),
        sa.Column("energy_score", sa.Float(), nullable=True),
        sa.Column("band", sa.String(length=20), nullable=True),
        sa.Column("coverage", sa.Float(), nullable=True),
        sa.Column("capacity_mw", sa.Float(), nullable=True),
        sa.Column("capacity_score", sa.Float(), nullable=True),
        sa.Column("service_score", sa.Float(), nullable=True),
        sa.Column("breakdown", sa.JSON(), nullable=True),
        sa.Column("model_version", sa.String(length=10), nullable=False),
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("(CURRENT_TIMESTAMP)"), nullable=False),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.text("(CURRENT_TIMESTAMP)"), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("period", name="uq_en_scores_period"),
    )
    op.create_index("ix_en_scores_period", "en_scores", ["period"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_en_scores_period", table_name="en_scores")
    op.drop_table("en_scores")
