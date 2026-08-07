"""rating_actions.metodologica — distinguir el cambio de vara del cambio de entidad

Cuando cambia la METODOLOGÍA, el tier de muchas entidades se mueve a la vez sin que haya
pasado nada en ellas. La recalibración de los indicadores de solidez (model_version 1.1 →
1.2) mueve a 44 de 46 entidades. Sin esta marca, el histórico registraría 44 downgrades
simultáneos y cualquier lectura posterior —un informe, una alerta, un comunicado— los
interpretaría como deterioro del sistema bancario dominicano en un trimestre.

``action_type`` se mantiene con el valor real (el tier efectivamente bajó); esta columna
registra la CAUSA, que es una dimensión distinta. Es el equivalente en banca de lo que en
seguros resuelve el ``MODEL_VERSION`` de ``insurance_ratings``.

Revision ID: d1a4c82f60be
Revises: c9f2e07b41da
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "d1a4c82f60be"
down_revision: Union[str, None] = "c9f2e07b41da"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("rating_actions",
                  sa.Column("metodologica", sa.Boolean(), nullable=False,
                            server_default=sa.false()))


def downgrade() -> None:
    op.drop_column("rating_actions", "metodologica")
