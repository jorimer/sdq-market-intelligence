"""data_api: ledger de activos + webhooks (Data API F3)

Revision ID: b7e1c4d9a306
Revises: a4d7e2f9b115
Create Date: 2026-07-22

Dos piezas de la Fase 3 (docs/SPEC_API_DATOS_PROPIETARIOS.md):

- ``data_api_asset_ledger``: cuándo apareció y cuándo se retiró cada activo del catálogo.
  Hace consultable ``/catalog/changes`` — sin esto la auto-extensión es invisible para un
  cliente que corre sin supervisión.
- ``data_api_webhook`` + ``data_api_webhook_delivery``: suscripción por llave a los
  eventos de "nuevo snapshot", con secreto para firmar (HMAC) y bitácora de entregas.

Aditivas; parity SQLite↔Postgres (String/Integer/DateTime/Boolean, UUID PK).
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "b7e1c4d9a306"
down_revision: Union[str, None] = "a4d7e2f9b115"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "data_api_asset_ledger",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.Column("asset_key", sa.String(length=255), nullable=False),
        sa.Column("kind", sa.String(length=20), nullable=False),
        sa.Column("sector_key", sa.String(length=40), nullable=False),
        sa.Column("code", sa.String(length=180), nullable=False),
        sa.Column("label", sa.String(length=255), nullable=True),
        sa.Column("first_seen_at", sa.DateTime(), nullable=False),
        sa.Column("last_seen_at", sa.DateTime(), nullable=False),
        sa.Column("retired_at", sa.DateTime(), nullable=True),
        sa.Column("last_exposed", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("last_quarantine", sa.String(length=255), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("asset_key", name="uq_data_api_asset_ledger_key"),
    )
    op.create_index(
        "ix_data_api_asset_ledger_seen", "data_api_asset_ledger",
        ["first_seen_at", "retired_at"],
    )

    op.create_table(
        "data_api_webhook",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.Column("api_key_id", sa.String(), nullable=False),
        sa.Column("url", sa.String(length=500), nullable=False),
        sa.Column("secret", sa.String(length=128), nullable=False),
        sa.Column("events", sa.String(length=255), nullable=False),
        sa.Column("active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("last_delivery_at", sa.DateTime(), nullable=True),
        sa.Column("consecutive_failures", sa.Integer(), nullable=False, server_default="0"),
        sa.ForeignKeyConstraint(["api_key_id"], ["data_api_key.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_data_api_webhook_key", "data_api_webhook", ["api_key_id"])

    op.create_table(
        "data_api_webhook_delivery",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.Column("webhook_id", sa.String(), nullable=False),
        sa.Column("event", sa.String(length=60), nullable=False),
        sa.Column("status_code", sa.Integer(), nullable=True),
        sa.Column("error", sa.String(length=255), nullable=True),
        sa.Column("attempted_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["webhook_id"], ["data_api_webhook.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_data_api_webhook_delivery_hook", "data_api_webhook_delivery",
        ["webhook_id", "attempted_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_data_api_webhook_delivery_hook", table_name="data_api_webhook_delivery")
    op.drop_table("data_api_webhook_delivery")
    op.drop_index("ix_data_api_webhook_key", table_name="data_api_webhook")
    op.drop_table("data_api_webhook")
    op.drop_index("ix_data_api_asset_ledger_seen", table_name="data_api_asset_ledger")
    op.drop_table("data_api_asset_ledger")
