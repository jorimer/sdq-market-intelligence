"""add super_admin role + access tier to users

Revision ID: c3f7a1b9d2e4
Revises: b6c4e1f2a3d8
Create Date: 2026-06-21

RBAC + administración de usuarios:
  - `super_admin`: rol por encima de admin (administración total de la plataforma).
    Jerárquico (super_admin ⊇ admin ⊇ analyst ⊇ viewer).
  - `tier` (access_tier: free/pro/enterprise): eje de monetización por nivel de
    acceso, independiente del rol. Declarado; no restringe contenido todavía.

Postgres: enum nativo (ADD VALUE en autocommit_block; CREATE TYPE para access_tier).
SQLite: Enum = VARCHAR → ALTER no nativo, columna simple.
"""
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "c3f7a1b9d2e4"
down_revision = "b6c4e1f2a3d8"
branch_labels = None
depends_on = None

_TIERS = ("free", "pro", "enterprise")


def upgrade() -> None:
    bind = op.get_bind()

    # 1) super_admin en el enum userrole (nativo PG; no-op en SQLite VARCHAR).
    #    ADD VALUE no puede usarse en la misma transacción → autocommit_block.
    if bind.dialect.name == "postgresql":
        with op.get_context().autocommit_block():
            op.execute("ALTER TYPE userrole ADD VALUE IF NOT EXISTS 'super_admin'")

    # 2) Tipo access_tier + columna tier (default free para filas existentes).
    if bind.dialect.name == "postgresql":
        postgresql.ENUM(*_TIERS, name="access_tier").create(bind, checkfirst=True)
        col_type = postgresql.ENUM(*_TIERS, name="access_tier", create_type=False)
    else:
        col_type = sa.Enum(*_TIERS, name="access_tier")

    op.add_column(
        "users",
        sa.Column("tier", col_type, nullable=False, server_default="free"),
    )


def downgrade() -> None:
    op.drop_column("users", "tier")
    if op.get_bind().dialect.name == "postgresql":
        op.execute("DROP TYPE IF EXISTS access_tier")
    # El valor 'super_admin' del enum userrole se deja (PG no soporta DROP VALUE
    # sin recrear el tipo; inocuo).
