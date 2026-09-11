"""Ensancha `source` y pasa `license` a TEXT en sector_observations.

Defecto REAL de producción, no preventivo: el primer sync del feed mensual del MIVHED
reventó con `StringDataRightTruncation` — la licencia declarada por el conector son 278
caracteres y la columna era VARCHAR(200). Los 9.769 tests estaban en verde: SQLite no aplica
el largo de un VARCHAR y PostgreSQL sí.

Medido sobre los 38 conectores del catálogo: la licencia más larga son 306 caracteres
(SISClient) y el `source` más largo, 82 (ONEConstructionClient) — con lo que `source`
VARCHAR(60) también habría reventado en cuanto un eje que no fuera construcción escribiera.

`license` pasa a TEXT y no a un VARCHAR más grande: es un párrafo del emisor, no un
identificador, y no tiene cota natural — cualquier número es la próxima truncación. En
PostgreSQL `text` y `varchar` rinden igual.

Revision ID: d5e9c3a71486
Revises: c4d8b2e6a370
Create Date: 2026-09-10
"""
import sqlalchemy as sa
from alembic import op

revision = "d5e9c3a71486"
down_revision = "c4d8b2e6a370"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # `batch_alter_table` y no `alter_column` a secas: SQLite no admite ALTER COLUMN y sin
    # el modo batch la migración pasa en PostgreSQL y falla en el entorno de desarrollo.
    with op.batch_alter_table("sector_observations") as batch:
        batch.alter_column("source", existing_type=sa.String(length=60),
                           type_=sa.String(length=120), existing_nullable=True)
        batch.alter_column("license", existing_type=sa.String(length=200),
                           type_=sa.Text(), existing_nullable=True)


def downgrade() -> None:
    # Bajar TRUNCA lo que no entre. La tabla es un feed re-ingestable (la ingesta borra y
    # reescribe), así que el dato se recupera corriendo el sync; se deja escrito para que
    # nadie lo descubra después.
    with op.batch_alter_table("sector_observations") as batch:
        batch.alter_column("license", existing_type=sa.Text(),
                           type_=sa.String(length=200), existing_nullable=True)
        batch.alter_column("source", existing_type=sa.String(length=120),
                           type_=sa.String(length=60), existing_nullable=True)
