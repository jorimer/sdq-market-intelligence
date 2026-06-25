"""add subscription table (suscripción recurrente que concede tier, monetización B3)

Revision ID: a7e3f1c9b6d4
Revises: f3a2c9d4e7b1
Create Date: 2026-06-25

Una suscripción concede un AccessTier mientras está vigente (status active + dentro del
período). can_access la compone con el tier manual y los entitlements, sin mutar User.tier.
En B3b el webhook de PayPal hace upsert por (provider, provider_subscription_id). Escrita a
mano a partir de `shared/products/models.py`.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "a7e3f1c9b6d4"
down_revision: Union[str, None] = "f3a2c9d4e7b1"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "subscription",
        sa.Column("user_id", sa.String(), nullable=False),
        sa.Column("provider", sa.String(length=20), nullable=False),
        sa.Column("provider_subscription_id", sa.String(length=128), nullable=False),
        sa.Column("tier", sa.String(length=20), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("current_period_end", sa.DateTime(), nullable=True),
        sa.Column("started_at", sa.DateTime(), nullable=True),
        sa.Column("cancelled_at", sa.DateTime(), nullable=True),
        sa.Column("note", sa.String(length=255), nullable=True),
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("created_at", sa.DateTime(),
                  server_default=sa.text("(CURRENT_TIMESTAMP)"), nullable=False),
        sa.Column("updated_at", sa.DateTime(),
                  server_default=sa.text("(CURRENT_TIMESTAMP)"), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("provider", "provider_subscription_id",
                            name="uq_subscription_provider_id"),
    )
    op.create_index("ix_subscription_user", "subscription", ["user_id"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_subscription_user", table_name="subscription")
    op.drop_table("subscription")
