"""Registro de uso de las herramientas comerciales: una fila por corrida.

Las tres herramientas con costo variable real por corrida —Research a Medida, Deal Scoring
y Contexto de Marca— no tenían contador. No se podía responder cuántas veces se usó ninguna,
ni cuánto cuesta operarlas, y por tanto no se podía decidir nada sobre su empaque comercial.

Mide, no restringe: no hay cuota ni gate en esta fase. `llm_calls` no sirve para esto porque
cuenta LLAMADAS, y la relación con una corrida no es uno a uno.

Revision ID: b3c7f1a9d248
Revises: e2b8d0c5a731
Create Date: 2026-09-09
"""
import sqlalchemy as sa
from alembic import op

revision = "b3c7f1a9d248"
down_revision = "e2b8d0c5a731"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "tool_runs",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(),
                  nullable=False),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.func.now(),
                  nullable=False),
        sa.Column("herramienta", sa.String(length=40), nullable=False),
        sa.Column("accion", sa.String(length=60), nullable=False),
        sa.Column("user_id", sa.String(), nullable=True),
        # 200: el sujeto de una corrida de research es la PREGUNTA recortada, y una pregunta
        # de comprador pasa holgadamente de 60 caracteres. SQLite no aplica el largo de un
        # VARCHAR y Postgres sí: un tope corto acá no rompe ningún test y tumba el registro
        # en producción.
        sa.Column("sujeto", sa.String(length=200), nullable=True),
        sa.Column("periodo", sa.String(length=7), nullable=False),
        sa.Column("ok", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("latency_ms", sa.Integer(), nullable=True),
        sa.Column("detalle", sa.JSON(), nullable=True),
    )
    op.create_index("ix_tool_runs_herramienta", "tool_runs", ["herramienta"])
    op.create_index("ix_tool_runs_user_id", "tool_runs", ["user_id"])
    # Los dos usos reales: «corridas por herramienta en un mes» y «las de este rango».
    op.create_index("ix_tool_runs_periodo_herramienta", "tool_runs",
                    ["periodo", "herramienta"])
    op.create_index("ix_tool_runs_created", "tool_runs", ["created_at"])


def downgrade() -> None:
    op.drop_index("ix_tool_runs_created", table_name="tool_runs")
    op.drop_index("ix_tool_runs_periodo_herramienta", table_name="tool_runs")
    op.drop_index("ix_tool_runs_user_id", table_name="tool_runs")
    op.drop_index("ix_tool_runs_herramienta", table_name="tool_runs")
    op.drop_table("tool_runs")
