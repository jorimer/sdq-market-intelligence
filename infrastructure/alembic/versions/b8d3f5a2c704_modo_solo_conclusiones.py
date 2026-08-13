"""Modo «solo conclusiones»: el mazo aporta su lectura sin la pasada de visión.

Cuando las cifras llegan por la plantilla del proveedor, leer cada lámina como imagen deja
de tener sentido: lo que la planilla NO trae son las conclusiones y el contexto, y eso vive
en la capa de texto del PDF —unas pocas llamadas en vez de una por lámina—.

Revision ID: b8d3f5a2c704
Revises: a2c7e9f14b83
"""
import sqlalchemy as sa
from alembic import op

revision = "b8d3f5a2c704"
down_revision = "a2c7e9f14b83"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("brand_extractions", schema=None) as batch:
        batch.add_column(sa.Column("conclusions_only", sa.Boolean(), nullable=False,
                                   server_default=sa.false()))


def downgrade() -> None:
    with op.batch_alter_table("brand_extractions", schema=None) as batch:
        batch.drop_column("conclusions_only")
