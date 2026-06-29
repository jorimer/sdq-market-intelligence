"""add transition_score to en_scores (IRSE dimensión de transición)

Revision ID: a3f9e1c7d502
Revises: bb956705136c
Create Date: 2026-06-28

Penetración renovable de la matriz de generación (ONE) → tercera dimensión del IRSE.
Float nullable (puede faltar el dato de generación en un período → brecha honesta).
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "a3f9e1c7d502"
down_revision: Union[str, None] = "bb956705136c"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("en_scores", sa.Column("transition_score", sa.Float(), nullable=True))


def downgrade() -> None:
    op.drop_column("en_scores", "transition_score")
