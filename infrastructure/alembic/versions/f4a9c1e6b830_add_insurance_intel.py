"""add insurance_intel tables (SIS · SISALRIL)

Revision ID: f4a9c1e6b830
Revises: e1c4b7a9d260
Create Date: 2026-07-03

Insurance Intel module (SDQ Seguros), mirror of pension_intel. Four tables:
entities (insurers/ARS catalog), series (market/entity observations, ramo via
``dimension``), ratings (ISF), snapshots (market pulse output). UUID PK, parity
SQLite↔Postgres. Missing values NULL (never interpolated).
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "f4a9c1e6b830"
down_revision: Union[str, None] = "e1c4b7a9d260"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _ts_cols():
    return (
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("created_at", sa.DateTime(),
                  server_default=sa.text("(CURRENT_TIMESTAMP)"), nullable=False),
        sa.Column("updated_at", sa.DateTime(),
                  server_default=sa.text("(CURRENT_TIMESTAMP)"), nullable=False),
    )


def upgrade() -> None:
    op.create_table(
        "insurance_entities",
        sa.Column("slug", sa.String(length=40), nullable=False),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("entity_type", sa.String(length=20), nullable=False),
        sa.Column("entity_code", sa.String(length=20), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        *_ts_cols(),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("slug", name="uq_insurance_entity_slug"),
    )

    op.create_table(
        "insurance_series",
        sa.Column("series_code", sa.String(length=120), nullable=False),
        sa.Column("period", sa.String(length=10), nullable=False),
        sa.Column("value", sa.Float(), nullable=True),
        sa.Column("unit", sa.String(length=40), nullable=True),
        sa.Column("frequency", sa.String(length=20), nullable=True),
        sa.Column("entity_slug", sa.String(length=40), nullable=True),
        sa.Column("dimension", sa.String(length=40), nullable=True),
        sa.Column("source", sa.String(length=40), nullable=True),
        sa.Column("published_at", sa.Date(), nullable=True),
        sa.Column("license", sa.String(length=160), nullable=True),
        *_ts_cols(),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("series_code", "period", "entity_slug", "dimension",
                            name="uq_insurance_series_period_entity_dim"),
    )
    op.create_index("ix_insurance_series_code_period", "insurance_series",
                    ["series_code", "period"], unique=False)
    op.create_index("ix_insurance_series_entity", "insurance_series",
                    ["entity_slug"], unique=False)

    op.create_table(
        "insurance_ratings",
        sa.Column("entity_slug", sa.String(length=40), nullable=False),
        sa.Column("period", sa.String(length=10), nullable=False),
        sa.Column("overall_score", sa.Float(), nullable=True),
        sa.Column("band", sa.String(length=20), nullable=True),
        sa.Column("coverage", sa.Float(), nullable=True),
        sa.Column("dimensions", sa.JSON(), nullable=True),
        sa.Column("model_version", sa.String(length=10), nullable=False),
        *_ts_cols(),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("entity_slug", "period", name="uq_insurance_rating_entity_period"),
    )
    op.create_index("ix_insurance_rating_entity_period", "insurance_ratings",
                    ["entity_slug", "period"], unique=False)

    op.create_table(
        "insurance_snapshots",
        sa.Column("period", sa.String(length=10), nullable=False),
        sa.Column("headline", sa.JSON(), nullable=True),
        sa.Column("series_count", sa.Float(), nullable=True),
        sa.Column("entity_count", sa.Float(), nullable=True),
        sa.Column("model_version", sa.String(length=10), nullable=False),
        *_ts_cols(),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("period", name="uq_insurance_snapshot_period"),
    )


def downgrade() -> None:
    op.drop_table("insurance_snapshots")
    op.drop_index("ix_insurance_rating_entity_period", table_name="insurance_ratings")
    op.drop_table("insurance_ratings")
    op.drop_index("ix_insurance_series_entity", table_name="insurance_series")
    op.drop_index("ix_insurance_series_code_period", table_name="insurance_series")
    op.drop_table("insurance_series")
    op.drop_table("insurance_entities")
