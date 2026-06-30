"""add const_scores (Construction Intel — ICC)

Revision ID: e1c4b7a9d260
Revises: d7b3e9f1a4c8
Create Date: 2026-06-29

Índice de Construcción (ICC) sobre dato real MIVHED (licencias) + BCRD (PIB construcción).
Una fila por período (año completo). UUID PK, parity SQLite↔Postgres.
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "e1c4b7a9d260"
down_revision: Union[str, None] = "d7b3e9f1a4c8"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "const_scores",
        sa.Column("period", sa.String(length=10), nullable=False),
        sa.Column("icc_score", sa.Float(), nullable=True),
        sa.Column("band", sa.String(length=20), nullable=True),
        sa.Column("coverage", sa.Float(), nullable=True),
        sa.Column("permits", sa.Float(), nullable=True),
        sa.Column("sqm", sa.Float(), nullable=True),
        sa.Column("investment_dop", sa.Float(), nullable=True),
        sa.Column("prod_growth_3y", sa.Float(), nullable=True),
        sa.Column("breakdown", sa.JSON(), nullable=True),
        sa.Column("model_version", sa.String(length=10), nullable=False),
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("created_at", sa.DateTime(),
                  server_default=sa.text("(CURRENT_TIMESTAMP)"), nullable=False),
        sa.Column("updated_at", sa.DateTime(),
                  server_default=sa.text("(CURRENT_TIMESTAMP)"), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("period", name="uq_const_scores_period"),
    )
    op.create_index("ix_const_scores_period", "const_scores", ["period"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_const_scores_period", table_name="const_scores")
    op.drop_table("const_scores")
