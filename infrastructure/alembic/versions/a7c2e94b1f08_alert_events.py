"""alerts: eventos juzgados por el gate — publicados Y vetados (alert_events)

Fase B de docs/SPEC_ALERTA_ACCIONABLE.md.

**Por qué se guarda lo vetado.** Un veto silencioso se lee como que el eje no tenía nada que
avisar, que es la lectura opuesta a la verdadera. Con la fila y su ``veto_motivo``,
``GET /alerts/events`` puede decir «3 señales retenidas por frescura del dato» en vez de no
decir nada, y queda la serie para saber qué veto muerde más.

**``frescura`` es nullable a propósito, y no es descuido.** Son TRES estados: vigente,
vencida e **indeterminada**. Colapsarla a booleano no-nulo obligaría a elegir un default, y
cualquiera de los dos miente: `False` inventa un problema, `True` es exactamente cómo
producción publicó 19 días un Gini calculado con un score que ya no existía.

Sin ENUM de base (mismo motivo que la migración anterior: namespace global de tipos en
Postgres, verde en CI y deploy caído).

Revision ID: a7c2e94b1f08
Revises: d3f7b0a56e12
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "a7c2e94b1f08"
down_revision: Union[str, None] = "d3f7b0a56e12"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "alert_events",
        sa.Column("codigo", sa.String(length=20), nullable=False),
        sa.Column("sector_key", sa.String(length=40), nullable=False),
        sa.Column("subject", sa.String(length=120), nullable=False,
                  server_default=sa.text("''")),
        sa.Column("periodo", sa.String(length=20), nullable=False,
                  server_default=sa.text("''")),
        sa.Column("severidad", sa.String(length=10), nullable=False,
                  server_default=sa.text("'media'")),
        sa.Column("titulo", sa.String(length=200), nullable=False),
        sa.Column("cuerpo", sa.Text(), nullable=False, server_default=sa.text("''")),
        sa.Column("basis", sa.Text(), nullable=False, server_default=sa.text("''")),
        sa.Column("relaciones", sa.JSON(), nullable=True),
        sa.Column("valores", sa.JSON(), nullable=True),
        sa.Column("procedencia", sa.JSON(), nullable=True),
        sa.Column("frescura", sa.Boolean(), nullable=True),
        sa.Column("publicada", sa.Boolean(), nullable=False,
                  server_default=sa.false()),
        sa.Column("veto_motivo", sa.String(length=40), nullable=True),
        sa.Column("veto_detalle", sa.Text(), nullable=True),
        sa.Column("dedup_key", sa.String(length=200), nullable=False,
                  server_default=sa.text("''")),
        sa.Column("entregas", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("created_at", sa.DateTime(),
                  server_default=sa.text("(CURRENT_TIMESTAMP)"), nullable=False),
        sa.Column("updated_at", sa.DateTime(),
                  server_default=sa.text("(CURRENT_TIMESTAMP)"), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_alert_events_sector_subject", "alert_events",
                    ["sector_key", "subject"], unique=False)
    op.create_index("ix_alert_events_dedup", "alert_events", ["dedup_key"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_alert_events_dedup", table_name="alert_events")
    op.drop_index("ix_alert_events_sector_subject", table_name="alert_events")
    op.drop_table("alert_events")
