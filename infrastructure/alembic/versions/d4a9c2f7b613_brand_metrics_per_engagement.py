"""brand_intel: vocabulario de métricas por encargo, para estudios que no son trackers

El módulo trae un diccionario canónico de tracker de marca y las dos rutas de ingesta
rechazan lo que no esté en él — que es lo que impide que una etiqueta mal leída invente un
indicador, y también la razón de que un estudio que mida otra cosa viera rechazadas el
100% de sus celdas.

Un encargo que declara sus propias métricas se valida contra ellas; uno que no declara
ninguna sigue usando el diccionario de tracker, así que nada de lo ya cargado cambia.

``kind`` es el campo que sostiene la garantía y por eso lo aprueba una persona: decide qué
estadística es legítima, y solo ``proportion`` admite banda de confianza. Una métrica mal
tipada como proporción fabrica intervalos que no existen.

``funnel_order`` sustituye a la escalera constante: un tracker declara la suya, y un
estudio sin secuencia de conversión no declara ninguna, con lo que la invariante de
monotonía no encuentra nada que comprobar en vez de equivocarse sobre un estudio que no
entiende.

Revision ID: d4a9c2f7b613
Revises: c3e6b81f9a45
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "d4a9c2f7b613"
down_revision: Union[str, None] = "c3e6b81f9a45"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "brand_metrics",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("engagement_id", sa.String(), nullable=False),
        sa.Column("code", sa.String(length=60), nullable=False),
        sa.Column("label", sa.String(length=160), nullable=False),
        sa.Column("kind", sa.String(length=20), nullable=False, server_default="count"),
        sa.Column("is_core", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("higher_is_better", sa.Boolean(), nullable=False,
                  server_default=sa.true()),
        sa.Column("category_denominator", sa.Boolean(), nullable=False,
                  server_default=sa.false()),
        sa.Column("funnel_order", sa.Integer(), nullable=True),
        sa.Column("sort_order", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.Column("updated_at", sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("engagement_id", "code", name="uq_brand_metric_code"),
    )


def downgrade() -> None:
    op.drop_table("brand_metrics")
