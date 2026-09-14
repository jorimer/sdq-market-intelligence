"""Caché propia de la sección del delta de los feeds sub-anuales.

Hasta acá el delta mensual de construcción viajaba dentro de `product_report_cache`, cuya
huella es del payload ENTERO: cada mes nuevo del feed regeneraba el Deep Dive completo —seis
llamadas al modelo por un dato que solo cambia una sección—. Esta tabla se indexa por (eje,
feed, período del feed, nivel, idioma) y su huella cubre solo lo que la sección ve: el delta se
regenera cuando cambia SU período o SU receta, y el informe del índice sigue siendo HIT.

`feed_clave` (120) y `feed_period` (80) son más anchos que una clave y un período porque
admiten un compuesto (`a+b`, `2026-06+2026-03`) cuando el eje tiene más de un emisor en la
misma sección. PostgreSQL SÍ aplica el largo del VARCHAR.

Revision ID: a9f3c7d1e5b2
Revises: d5e9c3a71486
Create Date: 2026-09-12
"""
import sqlalchemy as sa
from alembic import op

revision = "a9f3c7d1e5b2"
down_revision = "d5e9c3a71486"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "feed_delta_cache",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.Column("sector_key", sa.String(length=40), nullable=False),
        sa.Column("feed_clave", sa.String(length=120), nullable=False),
        sa.Column("feed_period", sa.String(length=80), nullable=False),
        sa.Column("tier", sa.String(length=20), nullable=False),
        sa.Column("lang", sa.String(length=8), nullable=False, server_default="es"),
        sa.Column("fingerprint", sa.String(length=64), nullable=False),
        sa.Column("texto", sa.Text(), nullable=False),
        sa.UniqueConstraint("sector_key", "feed_clave", "feed_period", "tier", "lang",
                            name="uq_feed_delta_cache_key"),
    )
    op.create_index("ix_feed_delta_cache_key", "feed_delta_cache",
                    ["sector_key", "feed_clave", "feed_period", "tier", "lang"])


def downgrade() -> None:
    # Es una caché: bajar la tira y la siguiente entrega la regenera. No hay dato que perder.
    op.drop_index("ix_feed_delta_cache_key", table_name="feed_delta_cache")
    op.drop_table("feed_delta_cache")
