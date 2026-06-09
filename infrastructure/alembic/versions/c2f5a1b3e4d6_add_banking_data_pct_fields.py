"""add pre-computed SIB ratio (%) fields to banking_data

The credit scoring mixed values from endpoints in different units (balance in
pesos, indicadores/solvencia in millions), producing garbage for solvencia,
ROA/ROE, margen and equity/assets. The fix stores the SIB's pre-computed %
ratios directly (dimensionless) and lets the engine prefer them, while the rest
is computed from the balance in pesos. These columns hold those ratios.

Revision ID: c2f5a1b3e4d6
Revises: b7c1e9a2d3f4
Create Date: 2026-06-08
"""
import sqlalchemy as sa
from alembic import op

revision = "c2f5a1b3e4d6"
down_revision = "b7c1e9a2d3f4"
branch_labels = None
depends_on = None

_COLUMNS = [
    "solvencia_pct",
    "tier1_pct",
    "morosidad_pct",
    "cartera_vigente_pct",
    "cobertura_pct",
    "margen_pct",
    "cost_income_pct",
]


def upgrade() -> None:
    for col in _COLUMNS:
        op.add_column("banking_data", sa.Column(col, sa.Numeric(10, 4), nullable=True))


def downgrade() -> None:
    for col in _COLUMNS:
        op.drop_column("banking_data", col)
