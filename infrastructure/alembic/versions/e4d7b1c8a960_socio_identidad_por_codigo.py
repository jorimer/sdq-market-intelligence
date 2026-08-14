"""ti_partner_chapters: la identidad del socio es el CÓDIGO, no la etiqueta

Con el índice único por NOMBRE, la misma corriente entró dos veces cuando la lista fija en
español ("Estados Unidos", "Brasil", "México", "España") se reemplazó por la derivada de
Comtrade en inglés ("USA", "Brazil", "Mexico", "Spain"): mismo `partner_code`, distinta
etiqueta, dos filas. El panel reportaba 196 socios donde hay 192 y el ranking por valor
gastaba dos cupos en el mismo país.

Se deduplica por (period, partner_code, direction, chapter) conservando la fila más reciente
—la de la ingesta derivada, cuya etiqueta viene de la fuente— y el índice pasa al código.

Revision ID: e4d7b1c8a960
Revises: d1c8e4b90735
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "e4d7b1c8a960"
down_revision: Union[str, None] = "d1c8e4b90735"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_TABLA = "ti_partner_chapters"


def upgrade() -> None:
    bind = op.get_bind()
    insp = sa.inspect(bind)
    if _TABLA not in insp.get_table_names():
        return

    # 1 · Deduplicar: conservar UNA fila por (período, código, dirección, capítulo).
    #     `updated_at` desempata a favor de la ingesta más reciente; `id` es el desempate
    #     estable cuando la marca de tiempo empata.
    borradas = bind.execute(sa.text(f"""
        DELETE FROM {_TABLA}
         WHERE id NOT IN (
               SELECT keep_id FROM (
                   SELECT id AS keep_id,
                          ROW_NUMBER() OVER (
                              PARTITION BY period, partner_code, direction, chapter
                              ORDER BY updated_at DESC NULLS LAST, id DESC) AS rn
                     FROM {_TABLA}
               ) t WHERE rn = 1)
    """)).rowcount
    print(f"[socio-identidad-por-codigo] filas duplicadas eliminadas: {borradas}")

    # 2 · El índice pasa a la identidad real.
    nombres = {i["name"] for i in insp.get_indexes(_TABLA)}
    if "ix_ti_pc_unico" in nombres:
        op.drop_index("ix_ti_pc_unico", table_name=_TABLA)
    op.create_index("ix_ti_pc_unico", _TABLA,
                    ["period", "partner_code", "direction", "chapter"], unique=True)


def downgrade() -> None:
    insp = sa.inspect(op.get_bind())
    if _TABLA not in insp.get_table_names():
        return
    # No se re-duplican las filas borradas: el downgrade restaura la FORMA, no la basura.
    nombres = {i["name"] for i in insp.get_indexes(_TABLA)}
    if "ix_ti_pc_unico" in nombres:
        op.drop_index("ix_ti_pc_unico", table_name=_TABLA)
    op.create_index("ix_ti_pc_unico", _TABLA,
                    ["period", "partner", "direction", "chapter"], unique=True)
