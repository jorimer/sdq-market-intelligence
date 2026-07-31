"""brand_intel: cada entrega deja su lectura, y la observación pasa a ser una proyección

Un tracker reexpone sus olas anteriores en cada entrega, y las cifras no siempre son
idénticas: el proveedor corrige una base, revisa una ponderación, arregla un gráfico. Con
una sola fila por cifra, la segunda entrega tenía que sobrescribir a la primera, y eso
hacía que la verdad dependiera del orden en que el cliente subió los ficheros — cargar el
año en el orden en que aparecen las carpetas revertía en silencio cifras ya corregidas.

``brand_observation_readings`` guarda lo que dijo cada entrega, sin pisar nada.
``brand_observations`` queda como proyección: gana la lectura del mazo más reciente y el
resto permanece en el registro, que es lo que permite responder "¿esta cifra cambió?".

La precedencia usa la **añada** del mazo (la ola más reciente que contiene), no la fecha
de subida: cuál entrega es más nueva es un hecho del mazo, y un cliente que hoy sube el
atraso del año pasado no puede volverlo autoritativo por subirlo después.

``source_extraction_id`` en la observación apunta a la lectura vigente. Nullable: lo ya
cargado viene del libro Excel o de mazos anteriores a este cambio, y no hay forma honesta
de inventarle procedencia.

Revision ID: c3e6b81f9a45
Revises: b2d8f4a10c37
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "c3e6b81f9a45"
down_revision: Union[str, None] = "b2d8f4a10c37"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "brand_observations",
        sa.Column("source_extraction_id", sa.String(), nullable=True),
    )
    op.create_table(
        "brand_observation_readings",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("engagement_id", sa.String(), nullable=False),
        sa.Column("extraction_id", sa.String(), nullable=True),
        sa.Column("wave_id", sa.String(), nullable=False),
        sa.Column("brand_slug", sa.String(length=60), nullable=True),
        sa.Column("metric_code", sa.String(length=60), nullable=False),
        sa.Column("segment", sa.String(length=60), nullable=False,
                  server_default="total"),
        sa.Column("value", sa.Float(), nullable=False),
        sa.Column("base_n", sa.Integer(), nullable=True),
        sa.Column("unit", sa.String(length=20), nullable=False, server_default="pct"),
        sa.Column("deck_vintage", sa.String(length=30), nullable=True),
        sa.Column("source", sa.String(length=200), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.Column("updated_at", sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("extraction_id", "wave_id", "brand_slug", "metric_code",
                            "segment", name="uq_brand_reading"),
    )
    op.create_index("ix_brand_reading_key", "brand_observation_readings",
                    ["engagement_id", "wave_id", "brand_slug", "metric_code", "segment"])


def downgrade() -> None:
    op.drop_index("ix_brand_reading_key", table_name="brand_observation_readings")
    op.drop_table("brand_observation_readings")
    op.drop_column("brand_observations", "source_extraction_id")
