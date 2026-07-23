"""mm_series.nature: naturaleza estadística de cada serie

Revision ID: c2f8a4b7d391
Revises: b7e1c4d9a306
Create Date: 2026-07-23

Qué tipo de magnitud mide la serie —flow | stock | rate | index | unknown—, resuelto en la
ingesta con la unidad que declara el emisor. Es la corrección de raíz del error de
categoría del motor de momentum: sin este dato, cada consumidor adivinaba la
transformación y se aplicaba variación porcentual a todo, incluidas 122 series que YA son
porcentajes.

Nullable a propósito: las filas anteriores quedan en NULL, el motor las lee como
``unknown`` y no computa porcentajes sobre ellas —honesto— hasta que la próxima ingesta
las complete. Aditiva y reversible.
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "c2f8a4b7d391"
down_revision: Union[str, None] = "b7e1c4d9a306"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("mm_series", sa.Column("nature", sa.String(length=12), nullable=True))


def downgrade() -> None:
    op.drop_column("mm_series", "nature")
