"""billing: user.country + billing_transaction (desglose fiscal)

Revision ID: e7c3a1f9b204
Revises: d4f6b8c1e357
Create Date: 2026-07-09

Monetización Fase 4 — impuestos + factura. Dos cambios:
- ``users.country`` (ISO-2, nullable): país de facturación del cliente, define el trato
  fiscal (ITBIS RD vs exportación de servicios exenta). None → se resuelve como "DO".
- tabla ``billing_transaction``: el registro contable de cada cobro con el DESGLOSE al
  centavo (subtotal + impuesto = total), fuente de la factura desglosada. UUID PK, parity
  SQLite↔Postgres (Numeric para montos, DateTime naive vía server_default CURRENT_TIMESTAMP).
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "e7c3a1f9b204"
down_revision: Union[str, None] = "d4f6b8c1e357"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("users", sa.Column("country", sa.String(length=2), nullable=True))

    op.create_table(
        "billing_transaction",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("created_at", sa.DateTime(),
                  server_default=sa.text("(CURRENT_TIMESTAMP)"), nullable=False),
        sa.Column("updated_at", sa.DateTime(),
                  server_default=sa.text("(CURRENT_TIMESTAMP)"), nullable=False),
        sa.Column("user_id", sa.String(), nullable=False),
        sa.Column("sku", sa.String(length=80), nullable=False),
        sa.Column("kind", sa.String(length=20), nullable=False),
        sa.Column("provider", sa.String(length=20), nullable=False),
        sa.Column("provider_ref", sa.String(length=128), nullable=True),
        sa.Column("event_id", sa.String(length=128), nullable=True),
        sa.Column("currency", sa.String(length=3), server_default="USD", nullable=False),
        sa.Column("subtotal", sa.Numeric(precision=12, scale=2), nullable=False),
        sa.Column("tax_rate", sa.Numeric(precision=5, scale=2), server_default="0", nullable=False),
        sa.Column("tax_amount", sa.Numeric(precision=12, scale=2), server_default="0", nullable=False),
        sa.Column("total", sa.Numeric(precision=12, scale=2), nullable=False),
        sa.Column("tax_label", sa.String(length=40), nullable=True),
        sa.Column("tax_exempt", sa.Boolean(), server_default=sa.false(), nullable=False),
        sa.Column("country", sa.String(length=2), nullable=True),
        sa.Column("invoice_number", sa.String(length=40), nullable=True),
        sa.Column("status", sa.String(length=20), server_default="paid", nullable=False),
        sa.Column("note", sa.String(length=255), nullable=True),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_billing_transaction_user", "billing_transaction", ["user_id"])
    op.create_index("uq_billing_transaction_event", "billing_transaction",
                    ["provider", "event_id"], unique=True)
    op.create_index("uq_billing_transaction_invoice", "billing_transaction",
                    ["invoice_number"], unique=True)


def downgrade() -> None:
    op.drop_index("uq_billing_transaction_invoice", table_name="billing_transaction")
    op.drop_index("uq_billing_transaction_event", table_name="billing_transaction")
    op.drop_index("ix_billing_transaction_user", table_name="billing_transaction")
    op.drop_table("billing_transaction")
    op.drop_column("users", "country")
