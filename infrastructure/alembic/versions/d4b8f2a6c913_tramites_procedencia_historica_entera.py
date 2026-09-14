"""Las filas VIEJAS de trámites recuperan la procedencia entera que el sync les recortó.

Desde #940 (2026-08-25) hasta #1171 (2026-09-14), `tramites_sync._upsert` guardaba
`fuente[:40]` y `licencia[:120]` para caber en `sd_indicators`. La migración c7e2a9d4f153
agrandó las columnas y quitó el recorte, y la re-corrida del 2026-09-14 reescribió el período
2026-09; los meses anteriores siguieron publicando «Portal Único de Servicios del Gobierno D»
como fuente y una licencia cortada a mitad de la base legal que autoriza reutilizar el dato.

**Solo se toca lo que es EXACTAMENTE el recorte.** El texto del conector no cambió desde que
nació (un solo commit, bbf5f7da), así que toda fila recortada vale `SOURCE[:40]` o
`LICENSE[:120]` de hoy. Se reemplaza esa igualdad y nada más: una fila con otra procedencia,
o ya entera, no coincide y queda como está. Por eso la migración es idempotente.

Los textos van CONGELADOS acá y no importados de `shared.data.gobdo_tramites`: una migración
que importa código de la app cambia de significado cuando ese código cambia.
`modules/social_dev/tests/test_migracion_procedencia_tramites.py` exige que coincidan con los
del conector de hoy.

Revision ID: d4b8f2a6c913
Revises: c7e3a1f9d284
Create Date: 2026-09-14
"""
import sqlalchemy as sa
from alembic import op

revision = "d4b8f2a6c913"
down_revision = "c7e3a1f9d284"
branch_labels = None
depends_on = None

_TABLA = "sd_indicators"
_TOPE_SOURCE_VIEJO = 40
_TOPE_LICENSE_VIEJO = 120

SOURCE = "Portal Único de Servicios del Gobierno Dominicano (gob.do) — OGTIC"
LICENSE = ("gob.do (OGTIC) — catálogo de trámites del Portal Único de Servicios. Información "
           "pública dominicana: reutilizable con atribución por Ley 200-04, Decreto 103-22 y "
           "NORTIC A3. `robots.txt` permite el rastreo completo (Allow: /).")


def _completar(bind) -> dict:
    """Reemplaza la procedencia recortada por la entera. Devuelve cuántas filas tocó."""
    cambios = {}
    for columna, entero, tope in (("source", SOURCE, _TOPE_SOURCE_VIEJO),
                                  ("license", LICENSE, _TOPE_LICENSE_VIEJO)):
        cambios[columna] = bind.execute(sa.text(
            f"UPDATE {_TABLA} SET {columna} = :entero "
            f"WHERE {columna} = :recortado AND theme LIKE 'tramites%'"),
            {"entero": entero, "recortado": entero[:tope]}).rowcount
    return cambios


def upgrade() -> None:
    bind = op.get_bind()
    if _TABLA not in sa.inspect(bind).get_table_names():
        return
    print(f"[tramites-procedencia-historica] filas completadas: {_completar(bind)}")


def downgrade() -> None:
    # No se vuelve a recortar: devolver una licencia mutilada no restaura ningún estado útil,
    # y `c7e2a9d4f153` ya documenta qué pasa si se bajan las columnas. Sin efecto a propósito.
    pass
