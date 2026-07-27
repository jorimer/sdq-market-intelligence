"""sib_historical_financials: derived per-entity monthly financials

Wide table derived from sib_historical_ledger by the crosswalk
(modules.banking_score.sib_historical_crosswalk): one row per entity per month with
the indicator inputs authentically reconstructable from the accounting ledger. Keyed by
entidad_code (no banks FK) — the historical universe includes many long-exited entities.
See docs/SIB_HISTORICO_FASE1_DISENO.md §3.

Revision ID: e5a1c9d7f204
Revises: d3f6a2c8e1b9
Create Date: 2026-07-27
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "e5a1c9d7f204"
down_revision: Union[str, None] = "d3f6a2c8e1b9"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "sib_historical_financials",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("(CURRENT_TIMESTAMP)"), nullable=False),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.text("(CURRENT_TIMESTAMP)"), nullable=False),
        sa.Column("entidad_code", sa.String(length=64), nullable=False),
        sa.Column("entidad_nombre", sa.String(length=255), nullable=True),
        sa.Column("tipo_entidad", sa.String(length=96), nullable=True),
        sa.Column("sector", sa.String(length=32), nullable=True),
        sa.Column("fecha", sa.Date(), nullable=False),
        sa.Column("ano", sa.Integer(), nullable=False),
        sa.Column("mes", sa.Integer(), nullable=False),
        sa.Column("activos_totales", sa.Numeric(precision=22, scale=2), nullable=True),
        sa.Column("cartera_bruta", sa.Numeric(precision=22, scale=2), nullable=True),
        sa.Column("cartera_neta", sa.Numeric(precision=22, scale=2), nullable=True),
        sa.Column("provisiones", sa.Numeric(precision=22, scale=2), nullable=True),
        sa.Column("cartera_vencida_90d", sa.Numeric(precision=22, scale=2), nullable=True),
        sa.Column("depositos_totales", sa.Numeric(precision=22, scale=2), nullable=True),
        sa.Column("patrimonio", sa.Numeric(precision=22, scale=2), nullable=True),
        sa.Column("pasivos_totales", sa.Numeric(precision=22, scale=2), nullable=True),
        sa.Column("activos_liquidos", sa.Numeric(precision=22, scale=2), nullable=True),
        sa.Column("utilidad_neta", sa.Numeric(precision=22, scale=2), nullable=True),
        sa.Column("ingresos_financieros", sa.Numeric(precision=22, scale=2), nullable=True),
        sa.Column("gastos_financieros", sa.Numeric(precision=22, scale=2), nullable=True),
        sa.Column("gastos_operativos", sa.Numeric(precision=22, scale=2), nullable=True),
        sa.Column("margen_financiero_bruto", sa.Numeric(precision=22, scale=2), nullable=True),
        sa.Column("morosidad_pct", sa.Numeric(precision=10, scale=4), nullable=True),
        sa.Column("cobertura_pct", sa.Numeric(precision=12, scale=4), nullable=True),
        sa.Column("apalancamiento_pct", sa.Numeric(precision=10, scale=4), nullable=True),
        sa.Column("snapshot_date", sa.Date(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("entidad_code", "fecha", name="uq_sib_hist_fin_entity_fecha"),
    )
    op.create_index("ix_sib_hist_fin_fecha", "sib_historical_financials", ["fecha"])


def downgrade() -> None:
    op.drop_index("ix_sib_hist_fin_fecha", table_name="sib_historical_financials")
    op.drop_table("sib_historical_financials")
