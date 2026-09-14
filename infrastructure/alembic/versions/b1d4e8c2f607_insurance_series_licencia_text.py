"""`insurance_series.license` pasa a TEXT y `source` a 120: dos syncs de prod no persisten nada.

Defecto REAL de producción, visto el 2026-09-14 en `GET /operations/status`:
`sisalril-sfs-sync` (2026-09-02, 693 filas) y `ars-sync` (2026-09-04, 6.111 filas) fallan con
`StringDataRightTruncation`. La licencia ODbL que declaran los conectores de SISALRIL mide 245
caracteres y la columna es `VARCHAR(160)`. La consola mostraba el `last_result` de la corrida
buena anterior, así que el sync parecía sano: el error vivía en `status.error`. Prod sirve la
afiliación SFS hasta 2026-03 mientras el CNSS ya publica mayo.

No son dos conectores: son CUATRO los que escriben esta tabla, y los cuatro exceden 160
(`SISClient` 306, `SISALRILClient` 245, `SISALRILARSClient` 245, `SISSolvencyClient` 189).
`insurance-sync` e `insurance-solvency-sync` caerían en su próxima corrida.

Es el mismo defecto de #1160 (`sector_observations`) en otra tabla. `license` va a TEXT y no a
un VARCHAR más grande por la misma razón: es un párrafo del emisor, sin cota natural, y
cualquier número es la próxima truncación. `source` a 120, el mismo tope medido que
`sector_observations`.

Revision ID: b1d4e8c2f607
Revises: a9f3c7d1e5b2
Create Date: 2026-09-14
"""
import sqlalchemy as sa
from alembic import op

revision = "b1d4e8c2f607"
down_revision = "a9f3c7d1e5b2"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # `batch_alter_table`: SQLite no admite ALTER COLUMN y sin el modo batch la migración pasa
    # en PostgreSQL y falla en el entorno de desarrollo.
    with op.batch_alter_table("insurance_series") as batch:
        batch.alter_column("source", existing_type=sa.String(length=40),
                           type_=sa.String(length=120), existing_nullable=True)
        batch.alter_column("license", existing_type=sa.String(length=160),
                           type_=sa.Text(), existing_nullable=True)


def downgrade() -> None:
    # Bajar TRUNCA lo que no entre, y con las licencias vigentes los cuatro syncs de seguros
    # vuelven a fallar. Las series se recuperan re-corriendo los syncs; se deja escrito.
    with op.batch_alter_table("insurance_series") as batch:
        batch.alter_column("license", existing_type=sa.Text(),
                           type_=sa.String(length=160), existing_nullable=True)
        batch.alter_column("source", existing_type=sa.String(length=120),
                           type_=sa.String(length=40), existing_nullable=True)
