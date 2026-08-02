"""notifications: destino navegable por aviso (action_url)

El buzón in-app nacía sin destino: el click solo marcaba leída, aunque cada texto
pidiera "revisar en el tablero/monitor". ``action_url`` guarda la ruta interna del
frontend a la que lleva el click; nullable porque un aviso puramente informativo no
navega. Las filas viejas (NULL) se resuelven al servir por prefijo de título — no se
migran datos.

Revision ID: e5f1a7c2d938
Revises: c4d8e2f7a961
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "e5f1a7c2d938"
down_revision: Union[str, None] = "c4d8e2f7a961"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("notifications", sa.Column("action_url", sa.String(length=300),
                                             nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("notifications") as batch:
        batch.drop_column("action_url")
