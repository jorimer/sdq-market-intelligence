"""brand_intel: las conclusiones del proveedor como objeto

El módulo guardaba cifras. Con cifras solo se describe, y describir es lo que el proveedor
ya hizo. Para explicar sus conclusiones hay que tenerlas guardadas, con su texto literal y
la lámina donde están escritas — el recibo que permite citarlo sin ponerle palabras.

Revision ID: a1d5f8c3e206
Revises: f2c7a4d9b810
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "a1d5f8c3e206"
down_revision: Union[str, None] = "f2c7a4d9b810"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "brand_conclusions",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("engagement_id", sa.String(), nullable=False),
        sa.Column("extraction_id", sa.String(), nullable=True),
        sa.Column("page_number", sa.Integer(), nullable=False),
        sa.Column("claim", sa.Text(), nullable=False),
        sa.Column("kind", sa.String(length=20), nullable=False,
                  server_default="hallazgo"),
        sa.Column("subjects", sa.JSON(), nullable=True),
        sa.Column("subject_slugs", sa.JSON(), nullable=True),
        sa.Column("topic", sa.String(length=200), nullable=True),
        sa.Column("metric_code", sa.String(length=60), nullable=True),
        sa.Column("direction", sa.String(length=20), nullable=True),
        sa.Column("wave_label", sa.String(length=60), nullable=True),
        sa.Column("wave_code", sa.String(length=30), nullable=True),
        sa.Column("confident", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.Column("updated_at", sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_brand_conclusion_engagement", "brand_conclusions",
                    ["engagement_id", "kind"])


def downgrade() -> None:
    op.drop_index("ix_brand_conclusion_engagement", table_name="brand_conclusions")
    op.drop_table("brand_conclusions")
