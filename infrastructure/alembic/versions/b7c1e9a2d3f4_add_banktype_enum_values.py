"""add banktype enum values (corporacion_credito, cambiaria, fiduciaria)

BankType grew to 6 types in code, but Alembic autogenerate doesn't detect new
enum values, so the Postgres `banktype` type kept its original values. Inserting
a corporacion_credito bank failed with "invalid input value for enum banktype".
This adds the missing values. No-op on SQLite (enums stored as VARCHAR).

Revision ID: b7c1e9a2d3f4
Revises: 0989cf690bdb
Create Date: 2026-06-07
"""
from alembic import op

revision = "b7c1e9a2d3f4"
down_revision = "0989cf690bdb"
branch_labels = None
depends_on = None

_VALUES = [
    "banca_multiple",
    "aap",
    "banco_ahorro_credito",
    "corporacion_credito",
    "cambiaria",
    "fiduciaria",
]


def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        return  # SQLite stores enums as VARCHAR — nothing to alter
    # ALTER TYPE ... ADD VALUE must run outside a transaction block.
    with op.get_context().autocommit_block():
        for value in _VALUES:
            op.execute(f"ALTER TYPE banktype ADD VALUE IF NOT EXISTS '{value}'")


def downgrade() -> None:
    pass  # Postgres cannot drop enum values
