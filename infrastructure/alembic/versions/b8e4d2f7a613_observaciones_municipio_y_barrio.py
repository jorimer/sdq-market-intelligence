"""Agrega `municipio` y `barrio` a sector_observations y los suma a la unicidad.

Decisión del dueño (2026-09-15): el feed de construcción usa el municipio y el barrio/sector
que el CSV del MIVHED ya trae (103 municipios, 1.179 barrios). NOT NULL con centinela vacío,
como `provincia` y `tipologia`: en PostgreSQL dos NULL son distintos y la unicidad no valdría.

Revision ID: b8e4d2f7a613
Revises: e5c9a2d7b416
Create Date: 2026-09-15
"""
import sqlalchemy as sa
from alembic import op

revision = "b8e4d2f7a613"
down_revision = "e5c9a2d7b416"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("sector_observations") as batch:
        batch.add_column(sa.Column("municipio", sa.String(length=80), nullable=False,
                                   server_default=""))
        batch.add_column(sa.Column("barrio", sa.String(length=80), nullable=False,
                                   server_default=""))
        batch.drop_constraint("uq_sector_observations_punto", type_="unique")
        batch.create_unique_constraint(
            "uq_sector_observations_punto",
            ["sector_key", "series_code", "period", "provincia", "tipologia", "municipio",
             "barrio"])


def downgrade() -> None:
    # Las filas de municipio y barrio colisionarían con la unicidad vieja: se borran antes.
    # Son re-ingestables (el sync del MIVHED borra y reescribe su serie).
    op.execute("DELETE FROM sector_observations WHERE municipio <> '' OR barrio <> ''")
    with op.batch_alter_table("sector_observations") as batch:
        batch.drop_constraint("uq_sector_observations_punto", type_="unique")
        batch.create_unique_constraint(
            "uq_sector_observations_punto",
            ["sector_key", "series_code", "period", "provincia", "tipologia"])
        batch.drop_column("barrio")
        batch.drop_column("municipio")
