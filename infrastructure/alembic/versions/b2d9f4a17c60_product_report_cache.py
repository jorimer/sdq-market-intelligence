"""product_report_cache: caché de narrativas IA por (sector, nivel, ámbito, período, idioma)

Revision ID: b2d9f4a17c60
Revises: a1c7f2e9d3b5
Create Date: 2026-07-11

Tabla de caché para las narrativas generadas por el motor IA. Un HIT (fingerprint del
snapshot igual) sirve el reporte al instante en vez de regenerar (~15-90s). Aditiva;
parity SQLite↔Postgres (String/JSON, UUID PK como el resto de ``shared/products``).
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "b2d9f4a17c60"
down_revision: Union[str, None] = "a1c7f2e9d3b5"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "product_report_cache",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.Column("sector_key", sa.String(length=40), nullable=False),
        sa.Column("tier", sa.String(length=20), nullable=False),
        sa.Column("scope", sa.String(length=80), server_default="", nullable=False),
        sa.Column("period", sa.String(length=20), server_default="", nullable=False),
        sa.Column("lang", sa.String(length=8), server_default="es", nullable=False),
        sa.Column("fingerprint", sa.String(length=64), nullable=False),
        sa.Column("narratives", sa.JSON(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("sector_key", "tier", "scope", "period", "lang",
                            name="uq_product_report_cache_key"),
    )
    op.create_index("ix_product_report_cache_key", "product_report_cache",
                    ["sector_key", "tier", "scope", "period", "lang"])


def downgrade() -> None:
    op.drop_index("ix_product_report_cache_key", table_name="product_report_cache")
    op.drop_table("product_report_cache")
