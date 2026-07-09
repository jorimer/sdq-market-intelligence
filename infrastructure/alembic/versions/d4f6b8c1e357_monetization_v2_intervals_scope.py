"""monetization v2: tariff.interval + subscription.sku/interval

Modelo de pricing por-sector con periodicidad: la tarifa se resuelve por (sku, interval)
—once | monthly | annual— y la suscripción lleva el SKU vendido (insight:{sector} /
all_access / enterprise) que define el ALCANCE del acceso. El tarifario estaba vacío en
prod, así que no hay datos a migrar (el default 'once' cubre filas legacy si las hubiera).

Revision ID: d4f6b8c1e357
Revises: c3e5a7b9d240
Create Date: 2026-07-08
"""
import sqlalchemy as sa
from alembic import op

revision = "d4f6b8c1e357"
down_revision = "c3e5a7b9d240"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("tariff", sa.Column("interval", sa.String(length=10),
                                      nullable=False, server_default="once"))
    op.drop_index("ix_tariff_sku_window", table_name="tariff")
    op.create_index("ix_tariff_sku_window", "tariff", ["sku", "interval", "effective_from"])

    op.add_column("subscription", sa.Column("sku", sa.String(length=80), nullable=True))
    op.add_column("subscription", sa.Column("interval", sa.String(length=10), nullable=True))


def downgrade() -> None:
    op.drop_column("subscription", "interval")
    op.drop_column("subscription", "sku")
    op.drop_index("ix_tariff_sku_window", table_name="tariff")
    op.create_index("ix_tariff_sku_window", "tariff", ["sku", "effective_from"])
    op.drop_column("tariff", "interval")
