"""add billing_event table (payment webhook idempotency)

Dedupe key for payment-provider webhooks: a provider may resend the same event, and
processing it twice would grant duplicate access. Before applying a webhook we insert
``(provider, event_id)`` uniquely; a collision means "already processed → ignore".

Revision ID: c3e5a7b9d240
Revises: b2d4f6a8c135
Create Date: 2026-07-08
"""
import sqlalchemy as sa
from alembic import op

revision = "c3e5a7b9d240"
down_revision = "b2d4f6a8c135"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "billing_event",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.Column("provider", sa.String(length=20), nullable=False),
        sa.Column("event_id", sa.String(length=128), nullable=False),
        sa.Column("kind", sa.String(length=40), nullable=True),
        sa.Column("processed_at", sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("uq_billing_event", "billing_event", ["provider", "event_id"], unique=True)


def downgrade() -> None:
    op.drop_index("uq_billing_event", table_name="billing_event")
    op.drop_table("billing_event")
