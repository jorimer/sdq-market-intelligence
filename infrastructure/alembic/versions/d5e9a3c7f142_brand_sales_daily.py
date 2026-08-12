"""brand_intel: la venta diaria del operador, con transacciones y desglose por canal

Primera tabla del módulo que no es percepción. El estudio de mercado dice qué percibe el
consumidor; esto dice qué hizo. La columna que carga el valor analítico es el CONTEO DE
TRANSACCIONES: con venta y transacciones juntas, el movimiento de facturación se
descompone entre afluencia y gasto por visita, lectura que ninguna encuesta puede dar.

El cheque promedio no tiene columna: se computa al leer. Un derivado almacenado se
desincroniza en cuanto una fila se corrige.

Revision ID: d5e9a3c7f142
Revises: b7c4e1a9d302
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "d5e9a3c7f142"
down_revision: Union[str, None] = "b7c4e1a9d302"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_CHANNELS = ("drive_thru", "delivery", "counter")


def upgrade() -> None:
    cols = [
        sa.Column("engagement_id", sa.String(), nullable=False),
        sa.Column("business_date", sa.Date(), nullable=False),
        sa.Column("store_id", sa.String(length=40), nullable=False),
        sa.Column("store_name", sa.String(length=160), nullable=True),
        sa.Column("city", sa.String(length=80), nullable=True),
        sa.Column("zone", sa.String(length=80), nullable=True),
        sa.Column("sales", sa.Float(), nullable=True),
        sa.Column("sales_prior", sa.Float(), nullable=True),
        sa.Column("transactions", sa.Integer(), nullable=True),
        sa.Column("transactions_prior", sa.Integer(), nullable=True),
    ]
    for ch in _CHANNELS:
        cols += [
            sa.Column(f"sales_{ch}", sa.Float(), nullable=True),
            sa.Column(f"sales_{ch}_prior", sa.Float(), nullable=True),
            sa.Column(f"transactions_{ch}", sa.Integer(), nullable=True),
            sa.Column(f"transactions_{ch}_prior", sa.Integer(), nullable=True),
        ]
    cols += [
        sa.Column("currency", sa.String(length=8), nullable=False, server_default="DOP"),
        sa.Column("source_file", sa.String(length=300), nullable=True),
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("CURRENT_TIMESTAMP"),
                  nullable=False),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.text("CURRENT_TIMESTAMP"),
                  nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("engagement_id", "business_date", "store_id",
                            name="uq_brand_sales_daily"),
    ]
    op.create_table("brand_sales_daily", *cols)
    op.create_index("ix_brand_sales_lookup", "brand_sales_daily",
                    ["engagement_id", "business_date"])


def downgrade() -> None:
    op.drop_index("ix_brand_sales_lookup", table_name="brand_sales_daily")
    op.drop_table("brand_sales_daily")
