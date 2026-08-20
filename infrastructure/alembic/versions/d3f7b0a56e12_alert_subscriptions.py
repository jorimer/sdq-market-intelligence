"""alerts: watchlist del cliente (alert_subscriptions)

Fase A de docs/SPEC_ALERTA_ACCIONABLE.md. La plataforma no tenía el primitivo "esto me
interesa": ``shared/products/subscriptions.py`` es COBRO, no contenido, y el buzón de
notificaciones solo se dirigía a administradores.

Dos decisiones que quedan enterradas en el esquema y conviene leer acá:

- ``subject`` es NOT NULL con sentinela ``''`` (= todo el eje), no NULL. Dos NULL son
  DISTINTOS entre sí tanto en SQLite como en Postgres, así que un UNIQUE sobre una columna
  nullable NO impide dos vigilancias «todo el eje» del mismo usuario sobre el mismo eje —
  y cada una entregaría su propia copia de cada alerta. La API sigue exponiendo ``null``.
- **Sin ENUM de base.** Severidad, digest y canales son String validados en el servicio. Un
  ENUM de Postgres vive en un namespace global de tipos y una migración que lo recrea pasa
  verde en CI (SQLite lo ignora) y tumba el deploy; este repo ya lo pagó.

Revision ID: d3f7b0a56e12
Revises: c4e1a8b73d92
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "d3f7b0a56e12"
down_revision: Union[str, None] = "c4e1a8b73d92"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "alert_subscriptions",
        sa.Column("user_id", sa.String(), nullable=False),
        sa.Column("sector_key", sa.String(length=40), nullable=False),
        sa.Column("subject", sa.String(length=120), nullable=False,
                  server_default=sa.text("''")),
        sa.Column("rule_codes", sa.JSON(), nullable=True),
        sa.Column("min_severity", sa.String(length=10), nullable=False,
                  server_default=sa.text("'media'")),
        sa.Column("channels", sa.JSON(), nullable=False),
        sa.Column("digest", sa.String(length=10), nullable=False,
                  server_default=sa.text("'inmediato'")),
        sa.Column("active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("suspended_reason", sa.String(length=40), nullable=True),
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("created_at", sa.DateTime(),
                  server_default=sa.text("(CURRENT_TIMESTAMP)"), nullable=False),
        sa.Column("updated_at", sa.DateTime(),
                  server_default=sa.text("(CURRENT_TIMESTAMP)"), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("user_id", "sector_key", "subject",
                            name="uq_alert_subscription_user_sector_subject"),
    )
    op.create_index("ix_alert_subscriptions_user", "alert_subscriptions",
                    ["user_id"], unique=False)
    op.create_index("ix_alert_subscriptions_sector", "alert_subscriptions",
                    ["sector_key"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_alert_subscriptions_sector", table_name="alert_subscriptions")
    op.drop_index("ix_alert_subscriptions_user", table_name="alert_subscriptions")
    op.drop_table("alert_subscriptions")
