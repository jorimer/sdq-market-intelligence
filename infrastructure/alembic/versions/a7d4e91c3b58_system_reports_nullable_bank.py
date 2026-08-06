"""reports: los informes de sistema no cuelgan de un banco (bank_id nullable)

Los boletines transversales (criteria, wire, datawatch, sector_outlook) describen la
metodología o el sistema entero, no una entidad: no tienen banco al cual colgarse. Con
``bank_id`` NOT NULL no podían persistirse como ``Report``, así que sus endpoints
devolvían solo una ruta en el FS efímero del contenedor — sin ``report_id`` no había
forma de descargarlos por ``GET /reports/download/{report_id}``, y el archivo moría en
el siguiente redeploy. Se relaja la columna a nullable para que el informe de sistema
sea una fila de primera clase con su blob durable.

Revision ID: a7d4e91c3b58
Revises: e5f1a7c2d938
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "a7d4e91c3b58"
down_revision: Union[str, None] = "e5f1a7c2d938"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table("reports") as batch:
        batch.alter_column("bank_id", existing_type=sa.String(), nullable=True)


def downgrade() -> None:
    # Las filas de sistema (bank_id NULL) impedirían restaurar el NOT NULL: se borran
    # primero. Son informes regenerables, no dato primario.
    op.execute("DELETE FROM reports WHERE bank_id IS NULL")
    with op.batch_alter_table("reports") as batch:
        batch.alter_column("bank_id", existing_type=sa.String(), nullable=False)
