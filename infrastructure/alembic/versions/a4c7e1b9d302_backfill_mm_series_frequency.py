"""backfill mm_series.frequency desde la etiqueta del período

Revision ID: a4c7e1b9d302
Revises: d1f8b3c60a25
Create Date: 2026-09-03

La columna `mm_series.frequency` existe desde siempre y el ingestor no la poblaba: estaba
NULL en las 509 filas de dev. Cada lector la derivaba por su cuenta —la Data API lo hacía
sobre el CONJUNTO de períodos de cada serie, devolviendo "unknown" en cuanto uno solo
tuviera otro formato—. Desde `_upsert_records` las filas nuevas la traen; ésta cierra las
viejas, porque una columna a medias es peor que vacía: invita a confiar en ella.

**Data-only: no toca el esquema.** Y deriva de la ETIQUETA del período, que es el mismo
criterio que usa `shared.data.series_cadence.cadencia_de_periodo` en la ingesta — así una
fila vieja y una nueva del mismo período dicen lo mismo. Se escribe en SQL puro, con los
patrones que SQLite y PostgreSQL entienden por igual, para no arrastrar el ORM a una
migración.

El vocabulario es inglés porque es el que ya viaja al cliente por la Data API y el que
escriben los otros módulos que pueblan esta columna.

Lo que NO reconozca ningún patrón queda en NULL a propósito: "no sé de qué cadencia es" y
"es mensual" son cosas distintas, y rellenar con una suposición es exactamente lo que la
doctrina de la casa prohíbe.
"""
from typing import Sequence, Union

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "a4c7e1b9d302"
down_revision: Union[str, None] = "d1f8b3c60a25"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


# "2025-Q1" · "2025-01" · "2025". En LIKE, `_` es exactamente un carácter, así que la
# longitud ya discrimina el anual de los otros dos. Lo que NO discrimina sola es la máscara
# mensual: `____-__` también matchea `2025-Q1`, porque las dos tienen siete caracteres. Se
# excluye el trimestral de forma EXPLÍCITA en vez de confiar en que la sentencia trimestral
# corrió antes — un backfill cuyo resultado depende del orden de ejecución es una trampa
# para el próximo que agregue una cadencia en el medio.
_BACKFILL = [
    ("quarterly", "period LIKE '____-Q_'"),
    ("monthly", "period LIKE '____-__' AND period NOT LIKE '____-Q_'"),
    ("annual", "period LIKE '____'"),
]


def upgrade() -> None:
    for cadencia, condicion in _BACKFILL:
        op.execute(
            f"UPDATE mm_series SET frequency = '{cadencia}' "
            f"WHERE frequency IS NULL AND {condicion}"
        )


def downgrade() -> None:
    # Se revierte solo lo que esta migración pudo haber escrito. No se vacía la columna
    # entera: las filas que la ingesta escribió después no son asunto de este downgrade.
    op.execute(
        "UPDATE mm_series SET frequency = NULL "
        "WHERE frequency IN ('quarterly', 'monthly', 'annual')"
    )
