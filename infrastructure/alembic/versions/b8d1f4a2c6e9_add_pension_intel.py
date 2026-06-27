"""add pension_intel tables (SIPEN — fondos de pensiones)

Revision ID: b8d1f4a2c6e9
Revises: a7e3f1c9b6d4
Create Date: 2026-06-27

Data spine for the Pension Intel module (F0): the AFP catalog, the pension series
(system when entity_slug is NULL, per-AFP otherwise — the ONE/region dimension
pattern), and the computed system snapshot. Written by hand from
`modules/pension_intel/models/models.py`. See `tasks/PLAN_PENSIONES_SIPEN.md`.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "b8d1f4a2c6e9"
down_revision: Union[str, None] = "a7e3f1c9b6d4"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _ts_cols() -> list:
    return [
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("created_at", sa.DateTime(),
                  server_default=sa.text("(CURRENT_TIMESTAMP)"), nullable=False),
        sa.Column("updated_at", sa.DateTime(),
                  server_default=sa.text("(CURRENT_TIMESTAMP)"), nullable=False),
    ]


def upgrade() -> None:
    op.create_table(
        "pension_entities",
        sa.Column("slug", sa.String(length=40), nullable=False),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("afp_code", sa.String(length=20), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        *_ts_cols(),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("slug", name="uq_pension_entity_slug"),
    )

    op.create_table(
        "pension_series",
        sa.Column("series_code", sa.String(length=120), nullable=False),
        sa.Column("period", sa.String(length=10), nullable=False),
        sa.Column("value", sa.Float(), nullable=True),
        sa.Column("unit", sa.String(length=40), nullable=True),
        sa.Column("frequency", sa.String(length=20), nullable=True),
        sa.Column("entity_slug", sa.String(length=40), nullable=True),
        sa.Column("source", sa.String(length=40), nullable=True),
        sa.Column("published_at", sa.Date(), nullable=True),
        sa.Column("license", sa.String(length=160), nullable=True),
        *_ts_cols(),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("series_code", "period", "entity_slug",
                            name="uq_pension_series_period_entity"),
    )
    op.create_index("ix_pension_series_code_period", "pension_series",
                    ["series_code", "period"], unique=False)
    op.create_index("ix_pension_series_entity", "pension_series",
                    ["entity_slug"], unique=False)

    op.create_table(
        "pension_snapshots",
        sa.Column("period", sa.String(length=10), nullable=False),
        sa.Column("headline", sa.JSON(), nullable=True),
        sa.Column("series_count", sa.Float(), nullable=True),
        sa.Column("entity_count", sa.Float(), nullable=True),
        sa.Column("model_version", sa.String(length=10), nullable=False),
        *_ts_cols(),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("period", name="uq_pension_snapshot_period"),
    )


def downgrade() -> None:
    op.drop_table("pension_snapshots")
    op.drop_index("ix_pension_series_entity", table_name="pension_series")
    op.drop_index("ix_pension_series_code_period", table_name="pension_series")
    op.drop_table("pension_series")
    op.drop_table("pension_entities")
