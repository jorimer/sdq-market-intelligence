"""add source_suggestions table (Inteligencia de Fuentes)

Revision ID: 85147c12ac6c
Revises: d1f4c7a9e2b5
Create Date: 2026-06-28

Tablero de sugerencias de fuentes/información/sectores nuevos (Capa 3 del lazo de
auto-mejora). Escrita a mano a partir de `shared/source_intel/models.py`.
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "85147c12ac6c"
down_revision: Union[str, None] = "d1f4c7a9e2b5"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "source_suggestions",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.Column("kind", sa.String(length=20), nullable=False),
        sa.Column("title", sa.String(length=200), nullable=False),
        sa.Column("description", sa.Text(), nullable=False, server_default=""),
        sa.Column("origin", sa.String(length=20), nullable=False, server_default="manual"),
        sa.Column("proposed_by", sa.String(), nullable=True),
        sa.Column("target_axis", sa.String(length=40), nullable=True),
        sa.Column("target_gate", sa.String(length=8), nullable=True),
        sa.Column("status", sa.String(length=20), nullable=False, server_default="proposed"),
        sa.Column("evaluation", sa.JSON(), nullable=True),
        sa.Column("decision_note", sa.Text(), nullable=True),
        sa.ForeignKeyConstraint(["proposed_by"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_source_suggestions_status", "source_suggestions", ["status"])
    op.create_index("ix_source_suggestions_axis", "source_suggestions", ["target_axis"])


def downgrade() -> None:
    op.drop_index("ix_source_suggestions_axis", table_name="source_suggestions")
    op.drop_index("ix_source_suggestions_status", table_name="source_suggestions")
    op.drop_table("source_suggestions")
