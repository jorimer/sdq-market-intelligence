"""add pension_holdings table (cartera de inversiones de los fondos)

Revision ID: d1f4c7a9e2b5
Revises: c9e2a5b1d7f4
Create Date: 2026-06-28

Persists the pension funds' investment portfolio by issuer (SIPEN bulletin Cuadro 6.1).
Written by hand from modules/pension_intel/models/models.py. See tasks/PLAN_PENSIONES_CARTERA.md.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "d1f4c7a9e2b5"
down_revision: Union[str, None] = "c9e2a5b1d7f4"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "pension_holdings",
        sa.Column("period", sa.String(length=10), nullable=False),
        sa.Column("fund", sa.String(length=40), nullable=False),
        sa.Column("sub_sector", sa.String(length=120), nullable=True),
        sa.Column("issuer", sa.String(length=200), nullable=False),
        sa.Column("issuer_slug", sa.String(length=80), nullable=False),
        sa.Column("amount", sa.Float(), nullable=True),
        sa.Column("pct", sa.Float(), nullable=True),
        sa.Column("is_subtotal", sa.Boolean(), nullable=False),
        sa.Column("bank_entity_slug", sa.String(length=40), nullable=True),
        sa.Column("macro_class", sa.String(length=20), nullable=True),
        sa.Column("source", sa.String(length=40), nullable=True),
        sa.Column("published_at", sa.Date(), nullable=True),
        sa.Column("license", sa.String(length=160), nullable=True),
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("created_at", sa.DateTime(),
                  server_default=sa.text("(CURRENT_TIMESTAMP)"), nullable=False),
        sa.Column("updated_at", sa.DateTime(),
                  server_default=sa.text("(CURRENT_TIMESTAMP)"), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("period", "fund", "issuer_slug",
                            name="uq_pension_holding_period_fund_issuer"),
    )
    op.create_index("ix_pension_holding_period_fund", "pension_holdings",
                    ["period", "fund"], unique=False)
    op.create_index("ix_pension_holding_issuer", "pension_holdings",
                    ["issuer_slug"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_pension_holding_issuer", table_name="pension_holdings")
    op.drop_index("ix_pension_holding_period_fund", table_name="pension_holdings")
    op.drop_table("pension_holdings")
