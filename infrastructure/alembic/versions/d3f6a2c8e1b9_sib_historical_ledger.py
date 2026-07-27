"""sib_historical_ledger + datasource/periodtype enum values

Landing table for the SIB *Cronología SB* historical financial ledger — per-entity
monthly balance sheet (1947→) and income statement (1996→) published as public CSVs.
Long format (1 row = entity × period × chart-of-accounts line); the auditable source
that a downstream crosswalk pivots into banking_data (source=sib_historical).

Also adds the enum values consumed by that future crosswalk:
  - datasource.sib_historical
  - periodtype.monthly
Autogenerate doesn't detect new enum values; added explicitly. No-op on SQLite
(enums stored as VARCHAR). See docs/SIB_HISTORICO_FASE1_DISENO.md.

Revision ID: d3f6a2c8e1b9
Revises: c2f8a4b7d391
Create Date: 2026-07-27
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "d3f6a2c8e1b9"
down_revision: Union[str, None] = "c2f8a4b7d391"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "sib_historical_ledger",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("(CURRENT_TIMESTAMP)"), nullable=False),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.text("(CURRENT_TIMESTAMP)"), nullable=False),
        sa.Column("estado", sa.String(length=12), nullable=False),
        sa.Column("fecha", sa.Date(), nullable=False),
        sa.Column("ano", sa.Integer(), nullable=False),
        sa.Column("mes", sa.Integer(), nullable=False),
        sa.Column("periodicidad", sa.String(length=16), nullable=True),
        sa.Column("entidad_code", sa.String(length=64), nullable=False),
        sa.Column("entidad_nombre", sa.String(length=255), nullable=True),
        sa.Column("tipo_entidad", sa.String(length=96), nullable=True),
        sa.Column("sector", sa.String(length=32), nullable=True),
        sa.Column("tipo_capital", sa.String(length=48), nullable=True),
        sa.Column("nivel_1", sa.String(length=128), nullable=True),
        sa.Column("nivel_2", sa.String(length=200), nullable=True),
        sa.Column("nivel_3", sa.String(length=200), nullable=True),
        sa.Column("nivel_4", sa.String(length=200), nullable=True),
        sa.Column("monto", sa.Numeric(precision=22, scale=2), nullable=True),
        sa.Column("monto_desagregado", sa.Numeric(precision=22, scale=2), nullable=True),
        sa.Column("snapshot_date", sa.Date(), nullable=True),
        sa.Column("source_file", sa.String(length=80), nullable=True),
        sa.Column("row_key", sa.String(length=40), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("row_key", name="uq_sib_hist_row_key"),
    )
    op.create_index("ix_sib_hist_entity_fecha", "sib_historical_ledger", ["entidad_code", "fecha"])
    op.create_index("ix_sib_hist_estado_fecha", "sib_historical_ledger", ["estado", "fecha"])

    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        with op.get_context().autocommit_block():
            op.execute("ALTER TYPE datasource ADD VALUE IF NOT EXISTS 'sib_historical'")
            op.execute("ALTER TYPE periodtype ADD VALUE IF NOT EXISTS 'monthly'")


def downgrade() -> None:
    op.drop_index("ix_sib_hist_estado_fecha", table_name="sib_historical_ledger")
    op.drop_index("ix_sib_hist_entity_fecha", table_name="sib_historical_ledger")
    op.drop_table("sib_historical_ledger")
    # Postgres cannot drop enum values; left in place.
