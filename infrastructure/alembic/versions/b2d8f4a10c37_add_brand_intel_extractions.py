"""brand_intel: zona de espera para la extracción asistida de presentaciones

Las cifras leídas de un PDF aterrizan aquí, se validan contra invariantes estructurales y
solo una confirmación humana las promueve a ``brand_observations``. Nada de lo extraído
entra al análisis sin pasar por esta frontera.

Revision ID: b2d8f4a10c37
Revises: a1c7e93b2d04
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "b2d8f4a10c37"
down_revision: Union[str, None] = "a1c7e93b2d04"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "brand_extractions",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("engagement_id", sa.String(), nullable=False),
        sa.Column("document_name", sa.String(length=300), nullable=False),
        sa.Column("n_pages", sa.Integer(), nullable=True),
        sa.Column("status", sa.String(length=20), nullable=False, server_default="draft"),
        sa.Column("model_used", sa.String(length=60), nullable=True),
        sa.Column("method", sa.String(length=40), nullable=False, server_default="vision"),
        sa.Column("summary", sa.JSON(), nullable=True),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column("confirmed_by", sa.String(length=120), nullable=True),
        sa.Column("confirmed_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_brand_extraction_engagement", "brand_extractions",
                    ["engagement_id", "status"])

    op.create_table(
        "brand_extraction_cells",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("extraction_id", sa.String(), nullable=False),
        sa.Column("engagement_id", sa.String(), nullable=False),
        sa.Column("page_number", sa.Integer(), nullable=True),
        sa.Column("chart_label", sa.String(length=300), nullable=True),
        sa.Column("wave_code", sa.String(length=30), nullable=True),
        sa.Column("brand_slug", sa.String(length=60), nullable=True),
        sa.Column("metric_code", sa.String(length=60), nullable=False),
        sa.Column("segment", sa.String(length=60), nullable=False, server_default="total"),
        sa.Column("value", sa.Float(), nullable=False),
        sa.Column("base_n", sa.Integer(), nullable=True),
        sa.Column("unit", sa.String(length=20), nullable=False, server_default="pct"),
        sa.Column("source_method", sa.String(length=40), nullable=False,
                  server_default="vision"),
        sa.Column("validation", sa.String(length=30), nullable=False,
                  server_default="unchecked"),
        sa.Column("validation_note", sa.Text(), nullable=True),
        sa.Column("coordinate_value", sa.Float(), nullable=True),
        sa.Column("included", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_brand_cell_extraction", "brand_extraction_cells",
                    ["extraction_id", "validation"])


def downgrade() -> None:
    op.drop_index("ix_brand_cell_extraction", table_name="brand_extraction_cells")
    op.drop_table("brand_extraction_cells")
    op.drop_index("ix_brand_extraction_engagement", table_name="brand_extractions")
    op.drop_table("brand_extractions")
