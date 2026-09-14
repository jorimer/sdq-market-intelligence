"""`historical_deals`: cada corrida de scoring deja su fila, sin label, separada del registro curado.

Fase 4b del plan de entregables mensuales. Hasta acá la tabla solo se poblaba con «Guardar al
registro» (`POST /deals`) o con el seed, así que la curva de aprendizaje —la que decide si la
rúbrica gradúa a modelo entrenado— dependía de que alguien apretara un botón opcional. Los labels
se perdían por defecto.

- `origen` (`manual` | `automatico`): el registro curado no se mezcla con lo que registra la
  herramienta sola. `String(12)` y no un ENUM: un ENUM nuevo en PostgreSQL exige su propio
  `CREATE TYPE`, y SQLite no lo vería.
- `score_rubrica`, `score_confianza`, `scored_at`: el score de la corrida. NULL si no lo hubo.
- La unicidad pasa de `deal_name` a `(deal_name, origen)`: un deal puede estar en el curado Y en
  el automático. La curva de aprendizaje cuenta UNA fila por deal (prefiere la curada).

Las filas existentes quedan `manual` por `server_default`: son el registro curado.

Revision ID: c7e3a1f9d284
Revises: b1d4e8c2f607
Create Date: 2026-09-14
"""
import sqlalchemy as sa
from alembic import op

revision = "c7e3a1f9d284"
down_revision = "b1d4e8c2f607"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # `batch_alter_table`: SQLite no admite ALTER de restricciones y sin el modo batch la
    # migración pasa en PostgreSQL y falla en desarrollo.
    with op.batch_alter_table("historical_deals") as batch:
        batch.add_column(sa.Column("origen", sa.String(length=12), nullable=False,
                                   server_default="manual"))
        batch.add_column(sa.Column("score_rubrica", sa.Float(), nullable=True))
        batch.add_column(sa.Column("score_confianza", sa.String(length=20), nullable=True))
        batch.add_column(sa.Column("scored_at", sa.DateTime(), nullable=True))
        batch.drop_constraint("uq_historical_deals_name", type_="unique")
        batch.create_unique_constraint("uq_historical_deals_name_origen",
                                       ["deal_name", "origen"])


def downgrade() -> None:
    # Bajar BORRA las filas automáticas: sin la columna `origen`, un deal que está en el curado
    # y en el automático violaría la unicidad por nombre. Son corridas registradas por la
    # herramienta y no se recuperan re-scoreando (el score cambia con los anchors); se deja
    # escrito para que nadie lo descubra después.
    op.execute(sa.text("DELETE FROM historical_deals WHERE origen = 'automatico'"))
    with op.batch_alter_table("historical_deals") as batch:
        batch.drop_constraint("uq_historical_deals_name_origen", type_="unique")
        batch.create_unique_constraint("uq_historical_deals_name", ["deal_name"])
        batch.drop_column("scored_at")
        batch.drop_column("score_confianza")
        batch.drop_column("score_rubrica")
        batch.drop_column("origen")
