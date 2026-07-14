"""dgii_contribuyente_subclase: padrón DGII de contribuyentes activos por subclase CIIU

Revision ID: f1a2c6e9b7d4
Revises: b2d9f4a17c60
Create Date: 2026-07-14

Snapshot estructurado con historia (columna ``corte``) del padrón de contribuyentes
activos de DGII, agregado a nivel subclase CIIU (no las 190k filas crudas). Alimenta el
motor de research (§B de docs/SPEC_GATE_HONESTIDAD_Y_FUENTES_DGII.md). Aditiva; parity
SQLite↔Postgres (String/Integer/Date, UUID PK como el resto de ``shared/``).
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "f1a2c6e9b7d4"
down_revision: Union[str, None] = "b2d9f4a17c60"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "dgii_contribuyente_subclase",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.Column("corte", sa.Date(), nullable=False),
        sa.Column("subclase", sa.String(length=12), nullable=False),
        sa.Column("descripcion", sa.String(length=255), nullable=True),
        sa.Column("activos", sa.Integer(), server_default="0", nullable=False),
        sa.Column("activos_fisica", sa.Integer(), nullable=True),
        sa.Column("activos_juridica", sa.Integer(), nullable=True),
        sa.Column("source", sa.String(length=40), nullable=True),
        sa.Column("source_url", sa.String(length=600), nullable=True),
        sa.Column("license", sa.String(length=200), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("corte", "subclase", name="uq_dgii_contrib_corte_subclase"),
    )
    op.create_index("ix_dgii_contrib_corte", "dgii_contribuyente_subclase", ["corte"])


def downgrade() -> None:
    op.drop_index("ix_dgii_contrib_corte", table_name="dgii_contribuyente_subclase")
    op.drop_table("dgii_contribuyente_subclase")
