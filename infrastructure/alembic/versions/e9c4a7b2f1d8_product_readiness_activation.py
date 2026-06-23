"""add product_readiness and product_activation tables (monitor de productos)

Revision ID: e9c4a7b2f1d8
Revises: c3f7a1b9d2e4
Create Date: 2026-06-23

Persistencia del monitor de productización (P1): readiness calculado por (sector,
nivel) + estado de activación de acceso público. Escrita a mano a partir de
`shared/products/models.py` (equivalente a `autogenerate`).
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "e9c4a7b2f1d8"
down_revision: Union[str, None] = "c3f7a1b9d2e4"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "product_readiness",
        sa.Column("sector_key", sa.String(length=40), nullable=False),
        sa.Column("tier", sa.String(length=20), nullable=False),
        sa.Column("g1", sa.Float(), nullable=False, server_default="0"),
        sa.Column("g2", sa.Float(), nullable=False, server_default="0"),
        sa.Column("g3", sa.Float(), nullable=False, server_default="0"),
        sa.Column("g4", sa.Float(), nullable=False, server_default="0"),
        sa.Column("g5", sa.Float(), nullable=False, server_default="0"),
        sa.Column("readiness", sa.Float(), nullable=False, server_default="0"),
        sa.Column("detail", sa.JSON(), nullable=True),
        sa.Column("computed_at", sa.DateTime(), nullable=True),
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("created_at", sa.DateTime(),
                  server_default=sa.text("(CURRENT_TIMESTAMP)"), nullable=False),
        sa.Column("updated_at", sa.DateTime(),
                  server_default=sa.text("(CURRENT_TIMESTAMP)"), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("sector_key", "tier", name="uq_product_readiness_sector_tier"),
    )
    op.create_index("ix_product_readiness_sector", "product_readiness",
                    ["sector_key"], unique=False)

    op.create_table(
        "product_activation",
        sa.Column("sector_key", sa.String(length=40), nullable=False),
        sa.Column("tier", sa.String(length=20), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("activated_by", sa.String(), nullable=True),
        sa.Column("activated_at", sa.DateTime(), nullable=True),
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("created_at", sa.DateTime(),
                  server_default=sa.text("(CURRENT_TIMESTAMP)"), nullable=False),
        sa.Column("updated_at", sa.DateTime(),
                  server_default=sa.text("(CURRENT_TIMESTAMP)"), nullable=False),
        sa.ForeignKeyConstraint(["activated_by"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("sector_key", "tier", name="uq_product_activation_sector_tier"),
    )
    op.create_index("ix_product_activation_sector", "product_activation",
                    ["sector_key"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_product_activation_sector", table_name="product_activation")
    op.drop_table("product_activation")
    op.drop_index("ix_product_readiness_sector", table_name="product_readiness")
    op.drop_table("product_readiness")
