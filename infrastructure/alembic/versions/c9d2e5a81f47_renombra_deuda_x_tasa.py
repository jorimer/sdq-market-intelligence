"""Renombra `deuda_x_tasa` → `tasa_por_deuda`: el emisor ya la publica ponderada.

El nombre viejo declaraba una CUENTA que resultó equivocada. `tasaPorDeuda` del cubo de la
SIB no es una tasa: ya viene multiplicada por la deuda —es el numerador del promedio
ponderado—. Se comprobó contra el dato: una fila de ADEMI trae deuda 500.291 y tasaPorDeuda
18.435.617, treinta y siete veces mayor, y el cociente da 36,85%, que es la banda del
microcrédito dominicano.

El código multiplicaba otra vez por la deuda. Eso desbordó `Numeric(22,4)` y tumbó un
backfill de 107 minutos — pero el desbordamiento fue una SUERTE: con una columna más ancha
se habría guardado un número sin sentido y nadie se habría enterado.

Se renombra en vez de reusar el nombre porque una columna que dice `deuda_x_tasa` y contiene
otra cosa es la clase de trampa que este repo ya pagó varias veces.

La columna está VACÍA en producción: el backfill que la iba a llenar es el que falló, así
que renombrar no pierde ningún dato.

Revision ID: c9d2e5a81f47
Revises: b8c1e4f70d92
"""
from alembic import op

revision = "c9d2e5a81f47"
down_revision = "b8c1e4f70d92"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.alter_column("cartera_sectorial", "deuda_x_tasa", new_column_name="tasa_por_deuda")


def downgrade() -> None:
    op.alter_column("cartera_sectorial", "tasa_por_deuda", new_column_name="deuda_x_tasa")
