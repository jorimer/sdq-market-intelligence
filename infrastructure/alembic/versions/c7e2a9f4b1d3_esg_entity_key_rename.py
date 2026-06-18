"""rename esg_scores.sector_key to entity_key (IRC re-scoped to national)

The ESG IRC moved from per-sector to per-country (national + Caribbean panel), so
``esg_scores.sector_key`` now holds a country ISO3. Rename the column (and its
unique constraint / index) to ``entity_key`` for honest naming. The table is empty
in prod (the sector fixture was purged), so this is a safe rename.

Revision ID: c7e2a9f4b1d3
Revises: a1f4c2d8e9b0
Create Date: 2026-06-18
"""
from alembic import op

revision = "c7e2a9f4b1d3"
down_revision = "a1f4c2d8e9b0"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        return  # SQLite builds from the model directly in tests
    op.drop_constraint("uq_esg_sector_period", "esg_scores", type_="unique")
    op.drop_index("ix_esg_scores_sector_period", table_name="esg_scores")
    op.alter_column("esg_scores", "sector_key", new_column_name="entity_key")
    op.create_unique_constraint("uq_esg_entity_period", "esg_scores", ["entity_key", "period"])
    op.create_index("ix_esg_scores_entity_period", "esg_scores", ["entity_key", "period"])


def downgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        return
    op.drop_constraint("uq_esg_entity_period", "esg_scores", type_="unique")
    op.drop_index("ix_esg_scores_entity_period", table_name="esg_scores")
    op.alter_column("esg_scores", "entity_key", new_column_name="sector_key")
    op.create_unique_constraint("uq_esg_sector_period", "esg_scores", ["sector_key", "period"])
    op.create_index("ix_esg_scores_sector_period", "esg_scores", ["sector_key", "period"])
