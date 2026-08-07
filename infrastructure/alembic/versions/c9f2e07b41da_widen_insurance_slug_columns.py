"""Widen insurance slug columns 40 → 80

El slug oficial de AGRODOSA (``aseguradora_agropecuaria_dominicana_agrodosa``) tiene 44
caracteres y no entra en ``VARCHAR(40)``. En Postgres eso es un ``StringDataRightTruncation``
que aborta la transacción entera de ``score_and_persist`` y hace rollback de TODO el sync —
en SQLite (dev) el límite no se aplica, así que el defecto solo aparecía en producción.

Consecuencia real, medida el 2026-08-07: la tabla ``insurance_ratings`` quedó congelada en un
estado viejo (ni AGRODOSA ni Cuna Mutual —la primera del ranking— existían en ella), mientras
``/rankings``, que calcula en vivo, seguía dando resultados actuales. Los dos caminos divergían
porque la escritura venía fallando en silencio, no por diseño.

80 caracteres dan margen para los nombres largos del roster oficial sin volver a chocar.

Revision ID: c9f2e07b41da
Revises: a7d4e91c3b58
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "c9f2e07b41da"
down_revision: Union[str, None] = "a7d4e91c3b58"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_WIDEN = [
    ("insurance_entities", "slug", False),
    ("insurance_series", "entity_slug", True),
    ("insurance_ratings", "entity_slug", False),
]


def _es_sqlite() -> bool:
    """SQLite no aplica el ancho de VARCHAR (por eso el defecto solo existía en prod) y
    tampoco soporta ``ALTER COLUMN ... TYPE``. Ampliar ahí no es necesario ni posible:
    la migración es un no-op deliberado, no un caso sin cubrir."""
    return op.get_bind().dialect.name == "sqlite"


def upgrade() -> None:
    if _es_sqlite():
        return
    for table, col, nullable in _WIDEN:
        op.alter_column(table, col, existing_type=sa.String(40), type_=sa.String(80),
                        existing_nullable=nullable)


def downgrade() -> None:
    if _es_sqlite():
        return
    # Reversible sólo si ningún slug supera los 40 caracteres; con AGRODOSA cargada, el
    # downgrade fallaría por truncamiento. Se acota primero y luego se estrecha.
    for table, col, nullable in _WIDEN:
        op.execute(f"DELETE FROM {table} WHERE length({col}) > 40")
        op.alter_column(table, col, existing_type=sa.String(80), type_=sa.String(40),
                        existing_nullable=nullable)
