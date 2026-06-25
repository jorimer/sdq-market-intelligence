"""add tariff table (tarifario gestionado con vigencia por fechas, monetización B1)

Revision ID: f3a2c9d4e7b1
Revises: e2c5b8a4d1f6
Create Date: 2026-06-25

El precio deja de ser una constante en código: cada fila es el precio de un ``sku``
(insight | deep_dive:{sector} | special:{slug}) durante una ventana de fechas
(``effective_from`` / ``effective_to``). El "precio vigente" se resuelve por sku + ventana.
Escrita a mano a partir de `shared/billing/models.py`.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "f3a2c9d4e7b1"
down_revision: Union[str, None] = "e2c5b8a4d1f6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "tariff",
        sa.Column("sku", sa.String(length=80), nullable=False),
        sa.Column("currency", sa.String(length=3), nullable=False, server_default="USD"),
        sa.Column("amount", sa.Numeric(precision=12, scale=2), nullable=False),
        sa.Column("effective_from", sa.DateTime(), nullable=False),
        sa.Column("effective_to", sa.DateTime(), nullable=True),
        sa.Column("active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("label", sa.String(length=120), nullable=True),
        sa.Column("note", sa.String(length=255), nullable=True),
        sa.Column("created_by", sa.String(), nullable=True),
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("created_at", sa.DateTime(),
                  server_default=sa.text("(CURRENT_TIMESTAMP)"), nullable=False),
        sa.Column("updated_at", sa.DateTime(),
                  server_default=sa.text("(CURRENT_TIMESTAMP)"), nullable=False),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_tariff_sku", "tariff", ["sku"], unique=False)
    op.create_index("ix_tariff_sku_window", "tariff", ["sku", "effective_from"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_tariff_sku_window", table_name="tariff")
    op.drop_index("ix_tariff_sku", table_name="tariff")
    op.drop_table("tariff")
