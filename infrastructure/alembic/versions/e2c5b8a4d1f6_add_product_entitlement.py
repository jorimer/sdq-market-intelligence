"""add product_entitlement table (compra/otorgamiento por-producto, monetización B0)

Revision ID: e2c5b8a4d1f6
Revises: d1f4a9c7b3e2
Create Date: 2026-06-25

Acceso por-producto otorgado a un usuario, además del tier de suscripción: la "compra
puntual" de un (sector, nivel). En B0 lo otorga el admin a mano; en B1 lo crea el webhook
de pago. Escrita a mano a partir de `shared/products/models.py`.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "e2c5b8a4d1f6"
down_revision: Union[str, None] = "d1f4a9c7b3e2"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "product_entitlement",
        sa.Column("user_id", sa.String(), nullable=False),
        sa.Column("sector_key", sa.String(length=40), nullable=False),
        sa.Column("tier", sa.String(length=20), nullable=False),
        sa.Column("source", sa.String(length=20), nullable=False, server_default="manual"),
        sa.Column("granted_by", sa.String(), nullable=True),
        sa.Column("granted_at", sa.DateTime(), nullable=True),
        sa.Column("expires_at", sa.DateTime(), nullable=True),
        sa.Column("active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("note", sa.String(length=255), nullable=True),
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("created_at", sa.DateTime(),
                  server_default=sa.text("(CURRENT_TIMESTAMP)"), nullable=False),
        sa.Column("updated_at", sa.DateTime(),
                  server_default=sa.text("(CURRENT_TIMESTAMP)"), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.ForeignKeyConstraint(["granted_by"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_product_entitlement_user", "product_entitlement", ["user_id"],
                    unique=False)
    op.create_index("ix_product_entitlement_lookup", "product_entitlement",
                    ["user_id", "sector_key", "tier"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_product_entitlement_lookup", table_name="product_entitlement")
    op.drop_index("ix_product_entitlement_user", table_name="product_entitlement")
    op.drop_table("product_entitlement")
