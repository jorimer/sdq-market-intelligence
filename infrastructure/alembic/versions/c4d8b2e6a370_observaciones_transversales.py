"""Tabla transversal de observaciones sub-anuales por eje.

El mismo esquema estaba copiado tres veces (mm_series, insurance_series, pension_series) y
los demás ejes no tenían tabla de series. Ésta sirve al feed sub-anual de todos los ejes; las
tres existentes NO se migran, conviven.

Las dimensiones van NOT NULL con centinela vacío y no NULL: en PostgreSQL dos NULL son
distintos y una unicidad que las incluya no impediría duplicar la fila agregada.

Revision ID: c4d8b2e6a370
Revises: b3c7f1a9d248
Create Date: 2026-09-09
"""
import sqlalchemy as sa
from alembic import op

revision = "c4d8b2e6a370"
down_revision = "b3c7f1a9d248"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "sector_observations",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.Column("sector_key", sa.String(length=40), nullable=False),
        # 255: los códigos jerárquicos del motor de planillas llegan a ~73 caracteres y
        # PostgreSQL aplica el largo del VARCHAR aunque SQLite lo ignore.
        sa.Column("series_code", sa.String(length=255), nullable=False),
        sa.Column("period", sa.String(length=10), nullable=False),
        sa.Column("value", sa.Float(), nullable=True),
        sa.Column("unit", sa.String(length=40), nullable=True),
        sa.Column("frequency", sa.String(length=20), nullable=True),
        sa.Column("nature", sa.String(length=12), nullable=True),
        sa.Column("provincia", sa.String(length=80), nullable=False, server_default=""),
        sa.Column("tipologia", sa.String(length=80), nullable=False, server_default=""),
        sa.Column("source", sa.String(length=60), nullable=True),
        sa.Column("published_at", sa.Date(), nullable=True),
        sa.Column("license", sa.String(length=200), nullable=True),
        # La unicidad va DENTRO de create_table y no por ALTER: SQLite no admite añadir una
        # restricción a una tabla existente, así que un `create_unique_constraint` aparte
        # deja la tabla creada y la restricción no — sin error visible en el resumen.
        sa.UniqueConstraint("sector_key", "series_code", "period", "provincia", "tipologia",
                            name="uq_sector_observations_punto"),
    )
    op.create_index("ix_sector_observations_eje_serie_periodo", "sector_observations",
                    ["sector_key", "series_code", "period"])
    op.create_index("ix_sector_observations_eje_periodo", "sector_observations",
                    ["sector_key", "period"])


def downgrade() -> None:
    op.drop_index("ix_sector_observations_eje_periodo", table_name="sector_observations")
    op.drop_index("ix_sector_observations_eje_serie_periodo", table_name="sector_observations")
    # La unicidad se creó con la tabla; se va con ella.
    op.drop_table("sector_observations")
