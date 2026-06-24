"""add telecom_intel tables (IDT scores)

Revision ID: c4a1e8b2f9d3
Revises: b9d2e1f7a3c0
Create Date: 2026-06-24

"""
from typing import Sequence, Union

import sqlalchemy as sa

from alembic import op

revision: str = "c4a1e8b2f9d3"
down_revision: Union[str, None] = "b9d2e1f7a3c0"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "tel_scores",
        sa.Column("period", sa.String(length=10), nullable=False),
        sa.Column("telecom_score", sa.Float(), nullable=True),
        sa.Column("band", sa.String(length=20), nullable=True),
        sa.Column("coverage", sa.Float(), nullable=True),
        sa.Column("mobile_penetration", sa.Float(), nullable=True),
        sa.Column("internet_penetration", sa.Float(), nullable=True),
        sa.Column("broadband_share", sa.Float(), nullable=True),
        sa.Column("breakdown", sa.JSON(), nullable=True),
        sa.Column("model_version", sa.String(length=10), nullable=False),
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("(CURRENT_TIMESTAMP)"), nullable=False),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.text("(CURRENT_TIMESTAMP)"), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("period", name="uq_tel_scores_period"),
    )
    op.create_index("ix_tel_scores_period", "tel_scores", ["period"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_tel_scores_period", table_name="tel_scores")
    op.drop_table("tel_scores")
