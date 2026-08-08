"""Perfil SDQ persistido en rating_results — los dos ejes junto al score

Perfil SDQ reemplaza la notación de un símbolo (`SDQ-AAA…SDQ-D`) por dos ejes independientes.
Hasta ahora se calculaba al vuelo desde los sub-componentes; persistirlo permite tres cosas
que el cálculo en vivo no da: servirlo sin recomputar, comparar períodos, y **recomputar el
histórico completo** en vez de re-etiquetarlo.

Sobre el histórico: `rating_results` ya guarda los 5 sub-scores por período, así que Perfil
SDQ es DERIVABLE hacia atrás — no hay que inventar un mapeo de `SDQ-AA+` a dos ejes, que no
existiría. El re-etiquetado retroactivo que decidió el dueño (§9) se implementa recomputando,
que es la única forma honesta de hacerlo.

`rating_tier` NO se elimina en esta migración: convive deprecado mientras la superficie migra.
Quitar la columna y los datos en el mismo paso que se introduce el reemplazo dejaría sin salida
si algo del reemplazo hay que revisar.

Revision ID: e5b71c9f4a02
Revises: d1a4c82f60be
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "e5b71c9f4a02"
down_revision: Union[str, None] = "d1a4c82f60be"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_COLUMNAS = [
    ("ejecucion_score", sa.Numeric(6, 2)),
    ("resiliencia_score", sa.Numeric(6, 2)),
    ("banda_ejecucion", sa.String(20)),
    ("banda_resiliencia", sa.String(20)),
]


def upgrade() -> None:
    for nombre, tipo in _COLUMNAS:
        op.add_column("rating_results", sa.Column(nombre, tipo, nullable=True))


def downgrade() -> None:
    for nombre, _tipo in _COLUMNAS:
        op.drop_column("rating_results", nombre)
