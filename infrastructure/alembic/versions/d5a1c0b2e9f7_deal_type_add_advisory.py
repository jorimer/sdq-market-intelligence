"""add 'advisory' to deal_type enum

Revision ID: d5a1c0b2e9f7
Revises: f8b3d1a6c904
Create Date: 2026-06-21

'advisory' es el tipo de deal dominante en la cartera SDQ (asesoría/mandato). Se
añade al enum nativo `deal_type` en Postgres; en SQLite el Enum es VARCHAR → no-op.
"""
from typing import Sequence, Union

from alembic import op

revision: str = "d5a1c0b2e9f7"
down_revision: Union[str, None] = "f8b3d1a6c904"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        # Postgres 12+ permite ADD VALUE dentro de una transacción si el valor no se
        # usa en la misma transacción. IF NOT EXISTS lo hace idempotente.
        op.execute("ALTER TYPE deal_type ADD VALUE IF NOT EXISTS 'advisory'")
    # SQLite: el Enum se almacena como VARCHAR → no requiere cambio.


def downgrade() -> None:
    # Postgres no soporta DROP VALUE de un enum sin recrear el tipo; se deja el valor
    # (inocuo). No-op para mantener el downgrade simple y seguro.
    pass
