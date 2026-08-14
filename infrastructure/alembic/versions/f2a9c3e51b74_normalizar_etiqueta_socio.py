"""ti_partner_chapters: UNA etiqueta por código de socio

La migración anterior deduplicó por `partner_code` —correcto— pero dejó la ETIQUETA como
estaba en cada fila superviviente. Con `updated_at` empatado entre filas de la misma corrida,
el desempate por `id` repartió los capítulos de un mismo país entre sus dos nombres: en
producción quedaron 52 capítulos bajo "USA" y 44 bajo "Estados Unidos".

Los totales seguían sumando bien (8.920 + 4.426 = 13.346 MM), pero la LECTURA es por nombre,
así que consultar "USA" devolvía la mitad de su comercio. Antes de deduplicar devolvía el
total completo: el arreglo empeoró la lectura, que es peor que el defecto original.

Se normaliza a UNA etiqueta por código: la de la fila más reciente, que es la que produce la
ingesta derivada de Comtrade.

Revision ID: f2a9c3e51b74
Revises: e4d7b1c8a960
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "f2a9c3e51b74"
down_revision: Union[str, None] = "e4d7b1c8a960"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_TABLA = "ti_partner_chapters"


def upgrade() -> None:
    bind = op.get_bind()
    if _TABLA not in sa.inspect(bind).get_table_names():
        return
    # Etiqueta canónica por código = la de la fila más reciente.
    filas = bind.execute(sa.text(f"""
        UPDATE {_TABLA} AS t
           SET partner = c.nombre
          FROM (SELECT DISTINCT ON (partner_code) partner_code, partner AS nombre
                  FROM {_TABLA}
                 ORDER BY partner_code, updated_at DESC NULLS LAST, id DESC) AS c
         WHERE t.partner_code = c.partner_code AND t.partner <> c.nombre
    """)).rowcount if bind.dialect.name == "postgresql" else _normalizar_generico(bind)
    print(f"[normalizar-etiqueta-socio] filas re-etiquetadas: {filas}")


def _normalizar_generico(bind) -> int:
    """SQLite no tiene DISTINCT ON ni UPDATE…FROM: se resuelve en dos pasos."""
    canon = bind.execute(sa.text(f"""
        SELECT partner_code, partner FROM {_TABLA} AS a
         WHERE a.id = (SELECT b.id FROM {_TABLA} AS b
                        WHERE b.partner_code = a.partner_code
                        ORDER BY b.updated_at DESC, b.id DESC LIMIT 1)
    """)).fetchall()
    n = 0
    for code, nombre in canon:
        n += bind.execute(
            sa.text(f"UPDATE {_TABLA} SET partner = :n "
                    f"WHERE partner_code = :c AND partner <> :n"),
            {"n": nombre, "c": code}).rowcount
    return n


def downgrade() -> None:
    # No se re-parten las etiquetas: el downgrade restaura el esquema, no el desorden.
    pass
