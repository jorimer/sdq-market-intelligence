"""add tpm_forecast_log table (live track record of the TPM model)

Stores each frozen forecast of the next TPM decision (XGBoost class probabilities + the
Taylor rule's implied rate) and, once the BCRD publishes the real decision, its scoring
(top-1 hit, multiclass Brier score, implied-level error). Prospective by design — this is
the live confidence signal, distinct from the historical backtest. JSON is portable across
SQLite (dev) and PostgreSQL (prod).

Revision ID: b2d4f6a8c135
Revises: a1c2e3f4b5d6
Create Date: 2026-07-08
"""
import sqlalchemy as sa
from alembic import op

revision = "b2d4f6a8c135"
down_revision = "a1c2e3f4b5d6"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "tpm_forecast_log",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.Column("as_of", sa.String(length=10), nullable=False),
        sa.Column("model_version", sa.String(length=50), nullable=True),
        sa.Column("prob_cut", sa.Float(), nullable=True),
        sa.Column("prob_hold", sa.Float(), nullable=True),
        sa.Column("prob_hike", sa.Float(), nullable=True),
        sa.Column("predicted_action", sa.String(length=10), nullable=True),
        sa.Column("implied_rate", sa.Float(), nullable=True),
        sa.Column("bias_pp", sa.Float(), nullable=True),
        sa.Column("tpm_vigente", sa.Float(), nullable=True),
        sa.Column("features", sa.JSON(), nullable=True),
        sa.Column("status", sa.String(length=20), nullable=False, server_default="pending"),
        sa.Column("matched_article_id", sa.Integer(), nullable=True),
        sa.Column("realized_action", sa.String(length=10), nullable=True),
        sa.Column("realized_tpm_level", sa.Float(), nullable=True),
        sa.Column("realized_date", sa.String(length=10), nullable=True),
        sa.Column("correct", sa.Boolean(), nullable=True),
        sa.Column("brier", sa.Float(), nullable=True),
        sa.Column("level_abs_error", sa.Float(), nullable=True),
        sa.Column("scored_at", sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_tpm_forecast_log_as_of", "tpm_forecast_log", ["as_of"])
    op.create_index("ix_tpm_forecast_log_status", "tpm_forecast_log", ["status"])


def downgrade() -> None:
    op.drop_index("ix_tpm_forecast_log_status", table_name="tpm_forecast_log")
    op.drop_index("ix_tpm_forecast_log_as_of", table_name="tpm_forecast_log")
    op.drop_table("tpm_forecast_log")
