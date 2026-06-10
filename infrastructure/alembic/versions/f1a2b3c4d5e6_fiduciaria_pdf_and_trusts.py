"""add DataSource.sib_pdf + fideicomiso (public trust) tables

Fiduciary submodel: a new DataSource value for audited-PDF lineage, plus the three
tables that hold public-trust data and their own health index (separate from the
bank rating tables — trusts are funds, not solvency-rated entities).

Revision ID: f1a2b3c4d5e6
Revises: d3a7c4e1f2b5
Create Date: 2026-06-10
"""
import sqlalchemy as sa
from alembic import op

revision = "f1a2b3c4d5e6"
down_revision = "d3a7c4e1f2b5"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()

    # 1) DataSource enum: add 'sib_pdf' (Postgres native enum; no-op on SQLite).
    if bind.dialect.name == "postgresql":
        with op.get_context().autocommit_block():
            op.execute("ALTER TYPE datasource ADD VALUE IF NOT EXISTS 'sib_pdf'")

    # 2) Trust tables.
    op.create_table(
        "fideicomisos",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("slug", sa.String(), nullable=True),
        sa.Column("fiduciaria_bank_id", sa.String(), sa.ForeignKey("banks.id"), nullable=True),
        sa.Column("segment", sa.String(), nullable=True),
        sa.Column("source_url", sa.String(), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=True),
        sa.UniqueConstraint("name", name="uq_fideicomiso_name"),
    )

    op.create_table(
        "fideicomiso_data",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.Column("fideicomiso_id", sa.String(), sa.ForeignKey("fideicomisos.id"), nullable=False),
        sa.Column("period_end", sa.Date(), nullable=False),
        sa.Column("period_type", sa.Enum("quarterly", "annual", name="periodtype"), nullable=True),
        sa.Column("activos_totales", sa.Numeric(20, 2), nullable=True),
        sa.Column("pasivos_totales", sa.Numeric(20, 2), nullable=True),
        sa.Column("pasivos_circulantes", sa.Numeric(20, 2), nullable=True),
        sa.Column("patrimonio_fideicomitido", sa.Numeric(20, 2), nullable=True),
        sa.Column("activos_liquidos", sa.Numeric(20, 2), nullable=True),
        sa.Column("resultado_periodo", sa.Numeric(20, 2), nullable=True),
        sa.Column("ingresos_operacionales", sa.Numeric(20, 2), nullable=True),
        sa.Column(
            "source",
            sa.Enum("manual", "sib_api", "csv_upload", "sib_pdf", name="datasource"),
            nullable=True,
        ),
        sa.UniqueConstraint("fideicomiso_id", "period_end", name="uq_fideicomiso_period"),
    )

    op.create_table(
        "fideicomiso_health_scores",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.Column("fideicomiso_id", sa.String(), sa.ForeignKey("fideicomisos.id"), nullable=False),
        sa.Column("period_end", sa.Date(), nullable=False),
        sa.Column("solvencia_score", sa.Numeric(6, 2), nullable=True),
        sa.Column("liquidez_score", sa.Numeric(6, 2), nullable=True),
        sa.Column("sostenibilidad_score", sa.Numeric(6, 2), nullable=True),
        sa.Column("overall_score", sa.Numeric(6, 2), nullable=True),
        sa.Column("health_band", sa.String(), nullable=True),
        sa.Column("segment", sa.String(), nullable=True),
        sa.UniqueConstraint("fideicomiso_id", "period_end", name="uq_fideicomiso_score_period"),
    )


def downgrade() -> None:
    op.drop_table("fideicomiso_health_scores")
    op.drop_table("fideicomiso_data")
    op.drop_table("fideicomisos")
    # Postgres cannot drop enum values; leave 'sib_pdf' in place.
