"""IRMP Fase A: mpr_country_variables.meta (IC + n_fuentes + 35 fuentes WGI-2025)

Revision ID: a1c7f2e9d3b5
Revises: f1e8d3b7a940
Create Date: 2026-07-10

Fase A del upgrade del IRMP (SDQ Macro & Country Risk). Columna ``meta`` JSON en
``mpr_country_variables`` para guardar, junto al score 0-100, la riqueza de la
revisión metodológica WGI 2025: error estándar, intervalo de confianza 90%,
número de fuentes y el desglose de las 35 fuentes subyacentes por país/año.
Aditivo y nullable; parity SQLite↔Postgres (sa.JSON).
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "a1c7f2e9d3b5"
down_revision: Union[str, None] = "f1e8d3b7a940"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "mpr_country_variables",
        sa.Column("meta", sa.JSON(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("mpr_country_variables", "meta")
