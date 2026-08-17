"""Reembolso: marca en la factura original + nota de crédito como comprobante propio

Revision ID: c4e1a8b73d92
Revises: b2d7f4a91c65
Create Date: 2026-08-17

Un reembolso no borra ni edita la factura: el comprobante se emitió y ya se declaró. Se marca
la original (``refunded_at``) y se emite una fila NUEVA de ``kind='credit_note'`` que apunta a
ella por ``credits_transaction_id`` y consume su propio correlativo de la secuencia 04. Las dos
se reportan en el Formato 607; la nota lleva a la original en «Comprobante Modificado».
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "c4e1a8b73d92"
down_revision: Union[str, None] = "b2d7f4a91c65"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table("billing_transaction") as batch:
        batch.add_column(sa.Column("refunded_at", sa.DateTime(), nullable=True))
        batch.add_column(sa.Column("credits_transaction_id", sa.String(), nullable=True))
    # Una factura tiene A LO SUMO una nota de crédito: el índice único hace que un reembolso
    # reentregado no pueda emitir un segundo comprobante sobre el mismo cobro.
    op.create_index("uq_billing_transaction_credits", "billing_transaction",
                    ["credits_transaction_id"], unique=True)


def downgrade() -> None:
    op.drop_index("uq_billing_transaction_credits", table_name="billing_transaction")
    with op.batch_alter_table("billing_transaction") as batch:
        batch.drop_column("credits_transaction_id")
        batch.drop_column("refunded_at")
