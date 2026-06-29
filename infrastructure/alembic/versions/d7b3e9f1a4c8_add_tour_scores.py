"""add tour_scores (Tourism Intel — ITT)

Revision ID: d7b3e9f1a4c8
Revises: c5d2f3a8b914
Create Date: 2026-06-29

Índice de Tracción Turística (ITT) sobre dato real ONE (datos.gob.do, llegadas vía
aérea de no residentes). Una fila por período (año). UUID PK, parity SQLite↔Postgres.
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "d7b3e9f1a4c8"
down_revision: Union[str, None] = "c5d2f3a8b914"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "tour_scores",
        sa.Column("period", sa.String(length=10), nullable=False),
        sa.Column("itt_score", sa.Float(), nullable=True),
        sa.Column("band", sa.String(length=20), nullable=True),
        sa.Column("coverage", sa.Float(), nullable=True),
        sa.Column("nonresident", sa.Float(), nullable=True),
        sa.Column("foreign", sa.Float(), nullable=True),
        sa.Column("breakdown", sa.JSON(), nullable=True),
        sa.Column("model_version", sa.String(length=10), nullable=False),
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("created_at", sa.DateTime(),
                  server_default=sa.text("(CURRENT_TIMESTAMP)"), nullable=False),
        sa.Column("updated_at", sa.DateTime(),
                  server_default=sa.text("(CURRENT_TIMESTAMP)"), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("period", name="uq_tour_scores_period"),
    )
    op.create_index("ix_tour_scores_period", "tour_scores", ["period"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_tour_scores_period", table_name="tour_scores")
    op.drop_table("tour_scores")
