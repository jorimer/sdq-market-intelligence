"""data_api: llaves de cliente + bitácora de uso (Data API F1)

Revision ID: a4d7e2f9b115
Revises: f1a2c6e9b7d4
Create Date: 2026-07-22

Cimiento de la Data API (docs/SPEC_API_DATOS_PROPIETARIOS.md §5): credencial
máquina-a-máquina con cuota, y bitácora por llamada que sirve de contador de cuota, de
auditoría y de detección de barrido del catálogo. Aditiva; parity SQLite↔Postgres
(String/Integer/DateTime/Boolean, UUID PK como el resto de ``shared/``).
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "a4d7e2f9b115"
down_revision: Union[str, None] = "f1a2c6e9b7d4"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "data_api_key",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.Column("user_id", sa.String(), nullable=False),
        sa.Column("name", sa.String(length=80), nullable=False),
        sa.Column("prefix", sa.String(length=16), nullable=False),
        sa.Column("secret_hash", sa.String(length=64), nullable=False),
        sa.Column("client_ref", sa.String(length=60), nullable=True),
        # Uso declarado del consumidor: "internal" (insumo de análisis propio; el dato no
        # sale hacia terceros) habilita recibir series de fuentes con licencia
        # no-comercial o share-alike. "external" es el default conservador.
        sa.Column("usage", sa.String(length=20), nullable=False, server_default="external"),
        sa.Column("rate_limit_per_minute", sa.Integer(), nullable=False, server_default="60"),
        sa.Column("quota_per_month", sa.Integer(), nullable=True),
        sa.Column("active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("expires_at", sa.DateTime(), nullable=True),
        sa.Column("last_used_at", sa.DateTime(), nullable=True),
        sa.Column("revoked_at", sa.DateTime(), nullable=True),
        sa.Column("revoked_by", sa.String(), nullable=True),
        sa.Column("note", sa.String(length=255), nullable=True),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.ForeignKeyConstraint(["revoked_by"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("prefix", name="uq_data_api_key_prefix"),
    )
    op.create_index("ix_data_api_key_user", "data_api_key", ["user_id"])

    op.create_table(
        "data_api_usage",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.Column("api_key_id", sa.String(), nullable=False),
        sa.Column("resource", sa.String(length=60), nullable=False),
        sa.Column("asset_key", sa.String(length=255), nullable=True),
        sa.Column("status_code", sa.Integer(), nullable=False),
        sa.Column("rows", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("latency_ms", sa.Integer(), nullable=True),
        sa.Column("as_of", sa.String(length=20), nullable=True),
        sa.Column("requested_at", sa.DateTime(), nullable=False),
        sa.Column("quota_period", sa.String(length=7), nullable=False),
        sa.ForeignKeyConstraint(["api_key_id"], ["data_api_key.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_data_api_usage_key_period", "data_api_usage", ["api_key_id", "quota_period"]
    )
    op.create_index(
        "ix_data_api_usage_key_time", "data_api_usage", ["api_key_id", "requested_at"]
    )


def downgrade() -> None:
    op.drop_index("ix_data_api_usage_key_time", table_name="data_api_usage")
    op.drop_index("ix_data_api_usage_key_period", table_name="data_api_usage")
    op.drop_table("data_api_usage")
    op.drop_index("ix_data_api_key_user", table_name="data_api_key")
    op.drop_table("data_api_key")
