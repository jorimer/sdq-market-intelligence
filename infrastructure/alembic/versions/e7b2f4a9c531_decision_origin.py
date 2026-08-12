"""brand_intel: el origen del compromiso, para la evaluación cara a cara

El cliente registra los planes de sus agencias y SDQ propone los suyos. La promesa
comercial es que ambos se evalúan con la misma vara, ola tras ola — y para reportar el
desempeño de cada fuente hay que poder distinguirlas. Sin este campo, la evaluación
comparada no existe.

Por defecto `cliente`: todo lo registrado hasta la fecha vino de sus planes.

Revision ID: e7b2f4a9c531
Revises: d5e9a3c7f142
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "e7b2f4a9c531"
down_revision: Union[str, None] = "d5e9a3c7f142"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("brand_decisions",
                  sa.Column("origin", sa.String(length=20), nullable=False,
                            server_default="cliente"))


def downgrade() -> None:
    op.drop_column("brand_decisions", "origin")
