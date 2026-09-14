"""`sd_indicators.license` pasa a TEXT y `source` a 120: la procedencia del Registro Único no entraba.

Lo encontró el guard generalizado de `shared/tests/test_lo_que_sqlite_no_vigila.py`, que mide
TODA tabla con procedencia contra los conectores que efectivamente la escriben (2026-09-14).
De las once tablas con `period` y `source`/`license`, esta es la única cuyo escritor no entra:
`tramites_sync` persiste la procedencia de `shared.data.gobdo_tramites`, que declara `SOURCE`
de 66 caracteres y `LICENSE` de 225 contra `VARCHAR(40)` y `VARCHAR(120)`.

A diferencia de `insurance_series` (#1169) no reventó en producción, y es PEOR: el sync
recortaba con `fuente[:40]` y `licencia[:120]`, así que el INSERT pasaba y se publicaba una
licencia cortada a mitad de la base legal que autoriza reutilizar el dato. El recorte se quita
en el mismo cambio; las filas ya persistidas se corrigen re-corriendo `tramites-registro-unico`
con `force`.

`license` va a TEXT (un párrafo del emisor sin cota natural) y `source` a 120, el mismo tope de
`sector_observations` e `insurance_series`.

Revision ID: c7e2a9d4f153
Revises: b1d4e8c2f607
Create Date: 2026-09-14
"""
import sqlalchemy as sa
from alembic import op

revision = "c7e2a9d4f153"
down_revision = "b1d4e8c2f607"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # `batch_alter_table`: SQLite no admite ALTER COLUMN y sin el modo batch la migración pasa
    # en PostgreSQL y falla en el entorno de desarrollo.
    with op.batch_alter_table("sd_indicators") as batch:
        batch.alter_column("source", existing_type=sa.String(length=40),
                           type_=sa.String(length=120), existing_nullable=True)
        batch.alter_column("license", existing_type=sa.String(length=120),
                           type_=sa.Text(), existing_nullable=True)


def downgrade() -> None:
    # Bajar TRUNCA en PostgreSQL lo que no entre (o falla, según el valor): con la procedencia
    # vigente del Registro Único el sync de trámites vuelve a no caber. Se deja escrito.
    with op.batch_alter_table("sd_indicators") as batch:
        batch.alter_column("license", existing_type=sa.Text(),
                           type_=sa.String(length=120), existing_nullable=True)
        batch.alter_column("source", existing_type=sa.String(length=120),
                           type_=sa.String(length=40), existing_nullable=True)
