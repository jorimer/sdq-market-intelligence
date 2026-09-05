"""rb_country_aggregates: almacén regional de banca por sistema nacional

El almacén del boletín trimestral «RD en contexto regional» (T-BR-4). Guarda métricas de
SISTEMAS nacionales, nunca de entidades: el motor de `banking_score` está calibrado contra
el panel dominicano de 46 entidades y no se transfiere a otros países.

**Escrita a mano a partir del autogenerate, y por qué.** El autogenerate propuso, además de
esta tabla, ~40 operaciones ajenas de drift acumulado entre los modelos y el esquema —
`alter_column` de timestamps en brand_*, cambios de largo en data_api_*, un renombre de
columna en esg_scores— y, entre ellas, TRES conversiones de VARCHAR a `sa.Enum`
(`users.role`, `banking_data.source`, `fideicomiso_data.source`). Eso es exactamente lo que
tumbó el deploy en `d1c8e4b90735`: en Postgres los tipos ENUM viven en un namespace GLOBAL
y CI no lo ve porque corre sobre SQLite, donde un Enum es un VARCHAR con CHECK. Una
migración que agrega una tabla no arrastra el drift de otras diez: se queda solo con lo
suyo. El drift sigue ahí y es trabajo aparte.

Revision ID: 7babe43b4afd
Revises: b2e9f4a71c85
Create Date: 2026-09-04 21:42:01.206682

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = '7babe43b4afd'
down_revision: Union[str, None] = 'b2e9f4a71c85'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "rb_country_aggregates",
        # PK como String y no UUID nativo: es lo que hace que SQLite (dev y CI) y
        # PostgreSQL (prod) se comporten igual sin ramas por dialecto.
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.Column("iso_code", sa.String(length=3), nullable=False),
        sa.Column("period_end", sa.Date(), nullable=False),
        sa.Column("metric", sa.String(length=60), nullable=False),
        sa.Column("value", sa.Float(), nullable=True),
        sa.Column("source", sa.String(length=30), nullable=False),
        sa.Column("license", sa.String(length=255), nullable=False),
        sa.Column("fetched_at", sa.Date(), nullable=True),
        # String y no Enum, a propósito: ver el encabezado. Las normas contables las fija
        # cada supervisor y cambian sin avisarnos (Brasil ya rompió su serie con la
        # Res. CMN 4966); un VARCHAR absorbe eso, un tipo ENUM exige migración.
        sa.Column("norma_contable", sa.String(length=80), nullable=False),
        sa.Column("meta", sa.JSON(), nullable=True),
        sa.UniqueConstraint("iso_code", "period_end", "metric", "source",
                            name="uq_rb_pais_periodo_metrica"),
    )
    op.create_index("ix_rb_pais_periodo", "rb_country_aggregates",
                    ["iso_code", "period_end"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_rb_pais_periodo", table_name="rb_country_aggregates")
    op.drop_table("rb_country_aggregates")
