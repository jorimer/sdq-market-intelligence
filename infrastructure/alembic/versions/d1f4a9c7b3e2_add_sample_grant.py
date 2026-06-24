"""add sample_grant table (muestra descargable una única vez por sector/nivel)

Revision ID: d1f4a9c7b3e2
Revises: c4a1e8b2f9d3
Create Date: 2026-06-24

Monetización (muestra de conversión): registra que un usuario descargó la muestra
de un (sector, nivel). La unicidad (user_id, sector_key, tier) enforca "una única
vez" por producto/nivel. Escrita a mano a partir de `shared/products/models.py`.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "d1f4a9c7b3e2"
down_revision: Union[str, None] = "c4a1e8b2f9d3"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "sample_grant",
        sa.Column("user_id", sa.String(), nullable=False),
        sa.Column("sector_key", sa.String(length=40), nullable=False),
        sa.Column("tier", sa.String(length=20), nullable=False),
        sa.Column("downloaded_at", sa.DateTime(), nullable=True),
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("created_at", sa.DateTime(),
                  server_default=sa.text("(CURRENT_TIMESTAMP)"), nullable=False),
        sa.Column("updated_at", sa.DateTime(),
                  server_default=sa.text("(CURRENT_TIMESTAMP)"), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("user_id", "sector_key", "tier",
                            name="uq_sample_grant_user_sector_tier"),
    )
    op.create_index("ix_sample_grant_user", "sample_grant", ["user_id"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_sample_grant_user", table_name="sample_grant")
    op.drop_table("sample_grant")
