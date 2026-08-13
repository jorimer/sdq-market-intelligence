"""El atributo como DIMENSIÓN propia, no empaquetado en el corte.

Un índice de atributo se mide POR atributo. Sin columna propia, los ocho atributos de una
rejilla caen en la misma coordenada (ola × marca × métrica × corte) y el detector de
duplicados los declara contradictorios entre sí: pasó con 144 celdas de una sola lámina del
mazo de Ola 5. La clave única de la observación se rehace para incluirlo.

Reversible: al bajar se quita la columna y se restaura la clave anterior. Ojo — bajar con
observaciones que solo se distinguen por atributo VIOLARÍA la clave vieja; se declara acá
porque una migración que no puede volver atrás sin pérdida tiene que decirlo.

Revision ID: f3a1c9d5e720
Revises: e7b2f4a9c531
"""
import sqlalchemy as sa
from alembic import op

revision = "f3a1c9d5e720"
down_revision = "e7b2f4a9c531"
branch_labels = None
depends_on = None

_OBS = "brand_observations"
_READ = "brand_observation_readings"
_CELL = "brand_extraction_cells"
_UQ_OBS = "uq_brand_observation"
_UQ_READ = "uq_brand_reading"
_COLS_OBS = ["engagement_id", "wave_id", "brand_slug", "metric_code", "segment"]
_COLS_READ = ["extraction_id", "wave_id", "brand_slug", "metric_code", "segment"]
_ATTR = "attribute"


def upgrade() -> None:
    # `batch_alter_table` porque SQLite no sabe alterar restricciones: recrea la tabla.
    for tabla, uq, cols in ((_OBS, _UQ_OBS, _COLS_OBS), (_READ, _UQ_READ, _COLS_READ)):
        with op.batch_alter_table(tabla, schema=None) as batch:
            batch.add_column(sa.Column(_ATTR, sa.String(length=120), nullable=True))
            batch.drop_constraint(uq, type_="unique")
            batch.create_unique_constraint(uq, [*cols, _ATTR])
    # La celda en revisión no tiene clave única: es un borrador, y dos lecturas de la misma
    # coordenada conviviendo es justo lo que el detector de duplicados necesita ver.
    with op.batch_alter_table(_CELL, schema=None) as batch:
        batch.add_column(sa.Column(_ATTR, sa.String(length=120), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table(_CELL, schema=None) as batch:
        batch.drop_column(_ATTR)
    for tabla, uq, cols in ((_READ, _UQ_READ, _COLS_READ), (_OBS, _UQ_OBS, _COLS_OBS)):
        with op.batch_alter_table(tabla, schema=None) as batch:
            batch.drop_constraint(uq, type_="unique")
            batch.create_unique_constraint(uq, cols)
            batch.drop_column(_ATTR)
