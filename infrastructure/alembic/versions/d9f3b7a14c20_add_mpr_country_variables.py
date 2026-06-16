"""add mpr_country_variables (IRMP sourced inputs store, e.g. WGI)

El Eje 4 scoreaba desde un dataset suministrado por el caller (fixture). Esta
tabla persiste valores de fuente por (país, período, variable) — el WGI-sync
escribe acá, y el dataset del IRMP se arma de datos reales.

Revision ID: d9f3b7a14c20
Revises: c5e9a2f81d40
Create Date: 2026-06-15
"""
from alembic import op
import sqlalchemy as sa

revision = "d9f3b7a14c20"
down_revision = "c5e9a2f81d40"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "mpr_country_variables",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("iso_code", sa.String(length=3), nullable=False),
        sa.Column("period", sa.String(length=10), nullable=False),
        sa.Column("variable", sa.String(length=60), nullable=False),
        sa.Column("value", sa.Float(), nullable=True),
        sa.Column("source", sa.String(length=20), nullable=False),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("iso_code", "period", "variable", name="uq_mpr_var_country_period"),
    )
    op.create_index("ix_mpr_var_country_period", "mpr_country_variables", ["iso_code", "period"])


def downgrade() -> None:
    op.drop_index("ix_mpr_var_country_period", table_name="mpr_country_variables")
    op.drop_table("mpr_country_variables")
