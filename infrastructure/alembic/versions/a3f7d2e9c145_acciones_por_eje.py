"""rating_actions: la acción POR EJE de Perfil SDQ (§9)

Un símbolo único se reemplaza por dos ejes, así que una acción de rating también se desdobla.
No hay traducción de ``SDQ-AA+`` a una etiqueta nueva: hay dos transiciones independientes,
y una entidad puede mejorar en Ejecución y deteriorarse en Resiliencia en el mismo período.

Las columnas son nullable y el histórico se puebla con la operación de backfill, no en la
migración: re-etiquetar 22 períodos es trabajo de datos, no de esquema, y conviene poder
re-correrlo sin tocar la estructura.

Revision ID: a3f7d2e9c145
Revises: e5b71c9f4a02
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "a3f7d2e9c145"
down_revision: Union[str, None] = "e5b71c9f4a02"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


_COLUMNAS = (
    ("banda_ejecucion_previa", sa.String(20)),
    ("banda_ejecucion_nueva", sa.String(20)),
    ("banda_resiliencia_previa", sa.String(20)),
    ("banda_resiliencia_nueva", sa.String(20)),
    ("ejecucion_delta", sa.Numeric(6, 2)),
    ("resiliencia_delta", sa.Numeric(6, 2)),
)


def _existentes() -> set:
    """Columnas ya presentes — la migración es idempotente a propósito.

    El entorno de dev quedó desalineado del histórico de alembic (ver memoria del proyecto),
    así que una migración que asume el estado exacto de la tabla falla ahí sin que haya nada
    roto en el esquema.
    """
    insp = sa.inspect(op.get_bind())
    return {c["name"] for c in insp.get_columns("rating_actions")}


def upgrade() -> None:
    ya = _existentes()
    for nombre, tipo in _COLUMNAS:
        if nombre not in ya:
            op.add_column("rating_actions", sa.Column(nombre, tipo, nullable=True))


def downgrade() -> None:
    ya = _existentes()
    for nombre, _tipo in reversed(_COLUMNAS):
        if nombre in ya:
            op.drop_column("rating_actions", nombre)
