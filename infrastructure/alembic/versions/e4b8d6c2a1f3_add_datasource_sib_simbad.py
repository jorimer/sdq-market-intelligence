"""add datasource enum value sib_simbad

The cambiaria fallback ingests from SIMBAD (public Superset of the SB) when the open
statistics API lacks a period; those rows carry source=sib_simbad for lineage. Alembic
autogenerate doesn't detect new enum values, so add it explicitly. No-op on SQLite
(enums stored as VARCHAR).

Revision ID: e4b8d6c2a1f3
Revises: b2c3d4e5f6a7
Create Date: 2026-06-14
"""
from alembic import op

revision = "e4b8d6c2a1f3"
down_revision = "b2c3d4e5f6a7"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        return  # SQLite stores enums as VARCHAR — nothing to alter
    with op.get_context().autocommit_block():
        op.execute("ALTER TYPE datasource ADD VALUE IF NOT EXISTS 'sib_simbad'")


def downgrade() -> None:
    pass  # Postgres cannot drop enum values
