"""alerts: cola de entrega por correo (alert_deliveries)

Fase C de docs/SPEC_ALERTA_ACCIONABLE.md.

**Por qué existe solo para el correo.** La notificación in-app *es* su propio registro: se
crea y ya está entregada. El correo tiene un estado intermedio que el buzón no tiene —«le
corresponde, todavía no salió»— y sin una fila que lo represente no hay resumen diario ni
reintento posible: un SMTP caído se comería el aviso en silencio.

``enviado_at IS NULL`` = pendiente. Es a la vez la cola del resumen y la del reintento, que
son la misma cosa: lo que no salió, sigue pendiente.

``digest`` se COPIA de la vigilancia al generar la entrega en vez de leerse al enviar: si el
cliente pasa de «inmediato» a «semanal», lo ya generado no debería cambiar de trato a mitad
de camino.

Sin ENUM de base (namespace global de tipos en Postgres: verde en CI y deploy caído).

Revision ID: b8d1f36c07a4
Revises: a7c2e94b1f08
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "b8d1f36c07a4"
down_revision: Union[str, None] = "a7c2e94b1f08"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "alert_deliveries",
        sa.Column("event_id", sa.String(), nullable=False),
        sa.Column("user_id", sa.String(), nullable=False),
        sa.Column("canal", sa.String(length=20), nullable=False,
                  server_default=sa.text("'email'")),
        sa.Column("digest", sa.String(length=10), nullable=False,
                  server_default=sa.text("'inmediato'")),
        sa.Column("enviado_at", sa.DateTime(), nullable=True),
        sa.Column("intentos", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("ultimo_error", sa.String(length=200), nullable=True),
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("created_at", sa.DateTime(),
                  server_default=sa.text("(CURRENT_TIMESTAMP)"), nullable=False),
        sa.Column("updated_at", sa.DateTime(),
                  server_default=sa.text("(CURRENT_TIMESTAMP)"), nullable=False),
        sa.ForeignKeyConstraint(["event_id"], ["alert_events.id"]),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("event_id", "user_id", "canal",
                            name="uq_alert_delivery_event_user_canal"),
    )
    op.create_index("ix_alert_deliveries_pendientes", "alert_deliveries",
                    ["user_id", "canal", "enviado_at"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_alert_deliveries_pendientes", table_name="alert_deliveries")
    op.drop_table("alert_deliveries")
