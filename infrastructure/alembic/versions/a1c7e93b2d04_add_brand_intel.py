"""brand_intel: capa de contexto de mercado por encargo

Primer módulo de la plataforma con datos PRIVADOS por cliente. ``engagement_id`` es la
llave de aislamiento en las seis tablas y va indexada en los caminos de consulta reales.

Revision ID: a1c7e93b2d04
Revises: d9f1a4c7e208
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "a1c7e93b2d04"
down_revision: Union[str, None] = "d9f1a4c7e208"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "brand_engagements",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("slug", sa.String(length=60), nullable=False),
        sa.Column("client_name", sa.String(length=200), nullable=False),
        sa.Column("focal_brand", sa.String(length=120), nullable=False),
        sa.Column("market", sa.String(length=80), nullable=False,
                  server_default="República Dominicana"),
        sa.Column("category", sa.String(length=80), nullable=True),
        sa.Column("research_provider", sa.String(length=120), nullable=True),
        sa.Column("organization_id", sa.String(length=64), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("slug", name="uq_brand_engagement_slug"),
    )

    op.create_table(
        "brand_waves",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("engagement_id", sa.String(), nullable=False),
        sa.Column("code", sa.String(length=30), nullable=False),
        sa.Column("label", sa.String(length=40), nullable=False),
        sa.Column("sort_order", sa.Integer(), nullable=False),
        sa.Column("period_date", sa.Date(), nullable=True),
        sa.Column("field_start", sa.Date(), nullable=True),
        sa.Column("field_end", sa.Date(), nullable=True),
        sa.Column("nominal_base", sa.Integer(), nullable=True),
        sa.Column("is_projection", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("engagement_id", "code", name="uq_brand_wave_code"),
    )
    op.create_index("ix_brand_wave_engagement", "brand_waves",
                    ["engagement_id", "sort_order"])

    op.create_table(
        "brand_entities",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("engagement_id", sa.String(), nullable=False),
        sa.Column("slug", sa.String(length=60), nullable=False),
        sa.Column("name", sa.String(length=120), nullable=False),
        sa.Column("is_focal", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("in_category_set", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("sort_order", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("engagement_id", "slug", name="uq_brand_entity_slug"),
    )

    op.create_table(
        "brand_observations",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("engagement_id", sa.String(), nullable=False),
        sa.Column("wave_id", sa.String(), nullable=False),
        sa.Column("brand_slug", sa.String(length=60), nullable=True),
        sa.Column("metric_code", sa.String(length=60), nullable=False),
        sa.Column("segment", sa.String(length=60), nullable=False, server_default="total"),
        sa.Column("value", sa.Float(), nullable=False),
        sa.Column("base_n", sa.Integer(), nullable=True),
        sa.Column("unit", sa.String(length=20), nullable=False, server_default="pct"),
        sa.Column("source", sa.String(length=200), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("engagement_id", "wave_id", "brand_slug", "metric_code",
                            "segment", name="uq_brand_observation"),
    )
    op.create_index("ix_brand_obs_lookup", "brand_observations",
                    ["engagement_id", "metric_code", "segment"])

    op.create_table(
        "brand_decisions",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("engagement_id", sa.String(), nullable=False),
        sa.Column("title", sa.String(length=300), nullable=False),
        sa.Column("rationale", sa.Text(), nullable=True),
        sa.Column("metric_code", sa.String(length=60), nullable=False),
        sa.Column("segment", sa.String(length=60), nullable=False, server_default="total"),
        sa.Column("brand_slug", sa.String(length=60), nullable=True),
        sa.Column("baseline_wave_id", sa.String(), nullable=False),
        sa.Column("baseline_value", sa.Float(), nullable=True),
        sa.Column("target_wave_id", sa.String(), nullable=True),
        sa.Column("success_threshold", sa.Float(), nullable=True),
        sa.Column("owner", sa.String(length=120), nullable=True),
        sa.Column("status", sa.String(length=20), nullable=False, server_default="open"),
        sa.Column("verdict_note", sa.Text(), nullable=True),
        sa.Column("observed_delta", sa.Float(), nullable=True),
        sa.Column("detectable_threshold", sa.Float(), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_brand_decision_engagement", "brand_decisions",
                    ["engagement_id", "status"])

    op.create_table(
        "brand_forecasts",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("engagement_id", sa.String(), nullable=False),
        sa.Column("target_wave_id", sa.String(), nullable=False),
        sa.Column("brand_slug", sa.String(length=60), nullable=True),
        sa.Column("metric_code", sa.String(length=60), nullable=False),
        sa.Column("segment", sa.String(length=60), nullable=False, server_default="total"),
        sa.Column("point", sa.Float(), nullable=False),
        sa.Column("lo", sa.Float(), nullable=False),
        sa.Column("hi", sa.Float(), nullable=False),
        sa.Column("rule", sa.String(length=40), nullable=False),
        sa.Column("issued_at_wave_id", sa.String(), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False, server_default="pending"),
        sa.Column("actual", sa.Float(), nullable=True),
        sa.Column("inside_band", sa.Boolean(), nullable=True),
        sa.Column("abs_error", sa.Float(), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_brand_forecast_pending", "brand_forecasts",
                    ["engagement_id", "status"])


def downgrade() -> None:
    op.drop_index("ix_brand_forecast_pending", table_name="brand_forecasts")
    op.drop_table("brand_forecasts")
    op.drop_index("ix_brand_decision_engagement", table_name="brand_decisions")
    op.drop_table("brand_decisions")
    op.drop_index("ix_brand_obs_lookup", table_name="brand_observations")
    op.drop_table("brand_observations")
    op.drop_table("brand_entities")
    op.drop_index("ix_brand_wave_engagement", table_name="brand_waves")
    op.drop_table("brand_waves")
    op.drop_table("brand_engagements")
