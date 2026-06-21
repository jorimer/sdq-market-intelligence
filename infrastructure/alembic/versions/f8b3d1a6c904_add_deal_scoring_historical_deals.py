"""add deal_scoring historical_deals table

Revision ID: f8b3d1a6c904
Revises: c7e2a9f4b1d3
Create Date: 2026-06-20

Registro de deals históricos (dataset de entrenamiento del Deal Scoring Engine,
DEAL-Agent-003). Escrita a mano a partir del modelo
`modules/deal_scoring/models/models.py` (equivalente a `autogenerate`).
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "f8b3d1a6c904"
down_revision: Union[str, None] = "c7e2a9f4b1d3"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


DEAL_TYPE = sa.Enum(
    "capital_raise", "real_estate", "ma_valuation", "debt_portfolio",
    "venture", "financing", "other", name="deal_type",
)
DEAL_SECTOR = sa.Enum(
    "real_estate", "tourism", "mining_energy", "technology", "fintech",
    "agriculture", "cpg", "other", name="deal_sector",
)
DEAL_STAGE = sa.Enum(
    "initial", "due_diligence", "term_sheet", "legal", name="deal_stage",
)
LABEL_CONFIDENCE = sa.Enum("alta", "media", "baja", name="label_confidence")


def upgrade() -> None:
    op.create_table(
        "historical_deals",
        sa.Column("deal_name", sa.String(length=200), nullable=False),
        sa.Column("deal_type", DEAL_TYPE, nullable=False),
        sa.Column("deal_size_usd", sa.Numeric(18, 2), nullable=True),
        sa.Column("equity_required_pct", sa.Numeric(5, 2), nullable=True),
        sa.Column("sector", DEAL_SECTOR, nullable=False),
        sa.Column("country", sa.String(length=2), nullable=False),
        sa.Column("deal_stage", DEAL_STAGE, nullable=True),
        sa.Column("days_since_first_contact", sa.Integer(), nullable=True),
        sa.Column("promoter_track_record", sa.Integer(), nullable=True),
        sa.Column("financial_quality", sa.Integer(), nullable=True),
        sa.Column("market_validation", sa.Integer(), nullable=True),
        sa.Column("regulatory_readiness", sa.Integer(), nullable=True),
        sa.Column("closed_successfully", sa.Boolean(), nullable=True),
        sa.Column("outcome_date", sa.Date(), nullable=True),
        sa.Column("source_folder", sa.Text(), nullable=True),
        sa.Column("label_confidence", LABEL_CONFIDENCE, nullable=False),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("created_at", sa.DateTime(),
                  server_default=sa.text("(CURRENT_TIMESTAMP)"), nullable=False),
        sa.Column("updated_at", sa.DateTime(),
                  server_default=sa.text("(CURRENT_TIMESTAMP)"), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("deal_name", name="uq_historical_deals_name"),
    )
    op.create_index("ix_historical_deals_type_country", "historical_deals",
                    ["deal_type", "country"], unique=False)
    op.create_index("ix_historical_deals_outcome", "historical_deals",
                    ["closed_successfully"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_historical_deals_outcome", table_name="historical_deals")
    op.drop_index("ix_historical_deals_type_country", table_name="historical_deals")
    op.drop_table("historical_deals")
    # Limpieza de tipos enum (no-op en SQLite; relevante en Postgres).
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        for e in (DEAL_TYPE, DEAL_SECTOR, DEAL_STAGE, LABEL_CONFIDENCE):
            e.drop(bind, checkfirst=True)
