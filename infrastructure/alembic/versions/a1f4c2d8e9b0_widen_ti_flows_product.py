"""widen ti_flows.product to Text

Real DGA customs data uses full HS chapter descriptions as the product label, and
some exceed 120 chars (up to ~285). The old String(120) silently held on SQLite
(dev) but raised StringDataRightTruncation on Postgres (prod). Widen to Text.

Revision ID: a1f4c2d8e9b0
Revises: d9f3b7a14c20
Create Date: 2026-06-18
"""
import sqlalchemy as sa
from alembic import op

revision = "a1f4c2d8e9b0"
down_revision = "d9f3b7a14c20"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        return  # SQLite ignores VARCHAR length; tests build from the model directly
    op.alter_column("ti_flows", "product",
                    type_=sa.Text(), existing_type=sa.String(length=120),
                    existing_nullable=False)


def downgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        return
    op.alter_column("ti_flows", "product",
                    type_=sa.String(length=120), existing_type=sa.Text(),
                    existing_nullable=False)
