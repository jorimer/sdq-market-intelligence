"""add cartera-quality ratio (%) fields to banking_data

Fase 2 (calidad de cartera): poblar indicadores antes N/D con dato real del SIB.
Estas columnas guardan ratios adimensionales calculados cada uno desde UN solo
endpoint del SIB (unit-safe, como las demás *_pct):
  - castigos_pct      = castigos / carteraTotal       (indicadores/morosidad-estresada)
  - exposicion_re_pct = deuda hipotecaria / deuda total (indicadores/riesgo-credito)

(hhi_sectorial_raw y hhi_ingresos_raw ya existen como columnas; este backfill los
puebla por primera vez con dato real.)

Revision ID: d3a7c4e1f2b5
Revises: c2f5a1b3e4d6
Create Date: 2026-06-09
"""
import sqlalchemy as sa
from alembic import op

revision = "d3a7c4e1f2b5"
down_revision = "c2f5a1b3e4d6"
branch_labels = None
depends_on = None

_COLUMNS = [
    "castigos_pct",
    "exposicion_re_pct",
]


def upgrade() -> None:
    for col in _COLUMNS:
        op.add_column("banking_data", sa.Column(col, sa.Numeric(10, 4), nullable=True))


def downgrade() -> None:
    for col in _COLUMNS:
        op.drop_column("banking_data", col)
