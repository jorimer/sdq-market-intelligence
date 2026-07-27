"""widen data_api ledger/usage key columns for long BCRD/SIB series codes

El ledger de activos (``data_api_asset_ledger``) copia ``mm_series.series_code``
en su columna ``code`` y le antepone "{sector}:{kind}:" para formar ``asset_key``.
El motor Excel AI-native del BCRD (y el histórico SIB) emiten códigos jerárquicos
("bcrd.xls.bpagos.balanza_comercial...") que ya se ampliaron a VARCHAR(255) en
``mm_series`` (revisión b2c3d4e5f6a7). El ledger se quedó en VARCHAR(180)/255:

- ``code`` VARCHAR(180) desbordaba en Postgres (StringDataRightTruncation) y
  tumbaba el INSERT batch COMPLETO del sync del sector macro cada ~45 s, dejando
  el ledger sin actualizar e inundando los logs con WARNING de ``sdq.data_api``.
- ``asset_key`` VARCHAR(255) también se queda corto: es code (hasta 255) más el
  prefijo "{sector}:{kind}:" (~15 chars) → hasta ~270.
- ``label`` VARCHAR(255): la etiqueta cae al code cuando no hay nombre curado.

Misma raíz en ``data_api_usage.asset_key`` (VARCHAR 255): el router guarda ahí el
mismo ``asset.key`` largo al registrar la llamada servida, así que un pedido de una
serie de código largo reventaba el commit de ``record_usage`` con el mismo error.

Se llevan las cuatro a VARCHAR(512): holgura cómoda sobre el máximo teórico (~270),
sin performance penalty frente a TEXT en Postgres. Aditiva; no toca datos.

SQLite es no-op: ignora la longitud declarada del VARCHAR y ``alter_column`` allí
exige rebuild por lotes — inútil cuando nada se está enforzando (parity con
b2c3d4e5f6a7).

Revision ID: d9f1a4c7e208
Revises: e5a1c9d7f204
Create Date: 2026-07-27
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "d9f1a4c7e208"
down_revision: Union[str, None] = "e5a1c9d7f204"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


# (tabla, columna, ancho viejo, nullable) — el nuevo ancho es 512 en todas.
_WIDENED = (
    ("data_api_asset_ledger", "asset_key", 255, False),
    ("data_api_asset_ledger", "code", 180, False),
    ("data_api_asset_ledger", "label", 255, True),
    ("data_api_usage", "asset_key", 255, True),
)


def upgrade() -> None:
    if op.get_bind().dialect.name == "sqlite":
        return  # SQLite ignora la longitud del VARCHAR; nada que enforzar ni alterar.
    for table, column, old_width, nullable in _WIDENED:
        op.alter_column(
            table, column,
            existing_type=sa.String(length=old_width),
            type_=sa.String(length=512),
            existing_nullable=nullable,
        )


def downgrade() -> None:
    if op.get_bind().dialect.name == "sqlite":
        return
    # Revertir puede fallar si algún valor persistido ya supera el ancho viejo.
    for table, column, old_width, nullable in _WIDENED:
        op.alter_column(
            table, column,
            existing_type=sa.String(length=512),
            type_=sa.String(length=old_width),
            existing_nullable=nullable,
        )
