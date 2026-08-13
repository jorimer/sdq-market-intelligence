"""ti_partner_chapters: comercio bilateral abierto por capítulo HS

Tabla propia y no una tercera clase de fila en ``ti_flows``: esa tabla ya mezcla capítulos del
mundo y comercio por país distinguidos por un centinela en ``product``, y tiene una ruta que
borra por período. Una fila socio × capítulo sería indistinguible por ``product`` de una del
mundo y cualquier consumidor que sume por producto contaría dos veces.

Revision ID: d1c8e4b90735
Revises: c9e4b1f70a26
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "d1c8e4b90735"
down_revision: Union[str, None] = "c9e4b1f70a26"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_TABLA = "ti_partner_chapters"


def upgrade() -> None:
    insp = sa.inspect(op.get_bind())
    if _TABLA in insp.get_table_names():
        return                      # idempotente: el entorno de dev va desalineado
    op.create_table(
        _TABLA,
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.Column("updated_at", sa.DateTime(), nullable=True),
        sa.Column("period", sa.String(10), nullable=False),
        sa.Column("partner", sa.String(80), nullable=False),
        sa.Column("partner_code", sa.String(8), nullable=True),
        sa.Column("direction", sa.Enum("export", "import", name="tradedirection"),
                  nullable=False),
        sa.Column("chapter", sa.String(2), nullable=False),
        sa.Column("value", sa.Float(), nullable=True),
        sa.Column("source", sa.String(40), nullable=True),
        sa.Column("license", sa.String(120), nullable=True),
    )
    op.create_index("ix_ti_pc_period_partner", _TABLA, ["period", "partner", "direction"])
    op.create_index("ix_ti_pc_unico", _TABLA,
                    ["period", "partner", "direction", "chapter"], unique=True)


def downgrade() -> None:
    insp = sa.inspect(op.get_bind())
    if _TABLA not in insp.get_table_names():
        return
    op.drop_index("ix_ti_pc_unico", table_name=_TABLA)
    op.drop_index("ix_ti_pc_period_partner", table_name=_TABLA)
    op.drop_table(_TABLA)
