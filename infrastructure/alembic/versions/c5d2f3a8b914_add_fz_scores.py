"""add fz_scores (Free Zones Intel — IZF)

Revision ID: c5d2f3a8b914
Revises: a3f9e1c7d502
Create Date: 2026-06-29

Índice de Atractividad de Zonas Francas (IZF) sobre dato real CNZFE (datos.gob.do).
Una fila por período (año). UUID PK, parity SQLite↔Postgres.
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "c5d2f3a8b914"
down_revision: Union[str, None] = "a3f9e1c7d502"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "fz_scores",
        sa.Column("period", sa.String(length=10), nullable=False),
        sa.Column("fz_score", sa.Float(), nullable=True),
        sa.Column("band", sa.String(length=20), nullable=True),
        sa.Column("coverage", sa.Float(), nullable=True),
        sa.Column("exports_musd", sa.Float(), nullable=True),
        sa.Column("investment_musd", sa.Float(), nullable=True),
        sa.Column("jobs", sa.Float(), nullable=True),
        sa.Column("companies", sa.Float(), nullable=True),
        sa.Column("breakdown", sa.JSON(), nullable=True),
        sa.Column("model_version", sa.String(length=10), nullable=False),
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("created_at", sa.DateTime(),
                  server_default=sa.text("(CURRENT_TIMESTAMP)"), nullable=False),
        sa.Column("updated_at", sa.DateTime(),
                  server_default=sa.text("(CURRENT_TIMESTAMP)"), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("period", name="uq_fz_scores_period"),
    )
    op.create_index("ix_fz_scores_period", "fz_scores", ["period"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_fz_scores_period", table_name="fz_scores")
    op.drop_table("fz_scores")
