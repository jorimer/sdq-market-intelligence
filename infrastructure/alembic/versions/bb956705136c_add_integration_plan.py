"""add integration_plan to source_suggestions (Capa 3 Increment 4)

Revision ID: bb956705136c
Revises: 85147c12ac6c
Create Date: 2026-06-28

Andamiaje de integración: plan/spec generado para una sugerencia aprobada (el dueño
gatea el build). JSON nullable.
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "bb956705136c"
down_revision: Union[str, None] = "85147c12ac6c"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("source_suggestions", sa.Column("integration_plan", sa.JSON(), nullable=True))


def downgrade() -> None:
    op.drop_column("source_suggestions", "integration_plan")
