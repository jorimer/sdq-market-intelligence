"""brand_intel: el canal de discrepancias con el proveedor

Cuando las cifras confirmadas sostienen lo contrario de lo que el estudio afirma, eso no
va al informe del cliente: se abre aquí y se discute con el proveedor primero. La
conclusión viaja copiada (claim + lámina) para sobrevivir a las relecturas de la entrega.

Revision ID: b7e2c9f4a153
Revises: a1d5f8c3e206
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "b7e2c9f4a153"
down_revision: Union[str, None] = "a1d5f8c3e206"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "brand_discrepancies",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("engagement_id", sa.String(), nullable=False),
        sa.Column("conclusion_id", sa.String(), nullable=True),
        sa.Column("claim", sa.Text(), nullable=False),
        sa.Column("page_number", sa.Integer(), nullable=False),
        sa.Column("subject_slugs", sa.JSON(), nullable=True),
        sa.Column("metric_code", sa.String(length=60), nullable=False),
        sa.Column("provider_direction", sa.String(length=20), nullable=False),
        sa.Column("data_note", sa.Text(), nullable=False),
        sa.Column("per_brand", sa.JSON(), nullable=True),
        sa.Column("status", sa.String(length=20), nullable=False,
                  server_default="abierta"),
        sa.Column("resolution_note", sa.Text(), nullable=True),
        sa.Column("updated_by", sa.String(length=120), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.Column("updated_at", sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_brand_discrepancy_engagement", "brand_discrepancies",
                    ["engagement_id", "status"])


def downgrade() -> None:
    op.drop_index("ix_brand_discrepancy_engagement", table_name="brand_discrepancies")
    op.drop_table("brand_discrepancies")
