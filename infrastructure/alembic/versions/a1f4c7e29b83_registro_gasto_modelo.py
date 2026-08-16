"""Registro de gasto del modelo: una fila por llamada, con su disparador.

El costo de cada llamada ya se calculaba y se escribía al log, pero nunca se guardaba, y
los logs del proveedor de despliegue solo conservan la versión vigente. Sin esta tabla,
una fuga de gasto solo se puede investigar leyendo código; con ella se consulta.

Revision ID: a1f4c7e29b83
Revises: f2a9c3e51b74
Create Date: 2026-08-16
"""
import sqlalchemy as sa
from alembic import op

revision = "a1f4c7e29b83"
down_revision = "f2a9c3e51b74"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "llm_calls",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(),
                  nullable=False),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.func.now(),
                  nullable=False),
        sa.Column("purpose", sa.String(length=30), nullable=False),
        sa.Column("model", sa.String(length=60), nullable=False),
        sa.Column("cost_usd", sa.Float(), nullable=False, server_default="0"),
        sa.Column("tokens_in", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("tokens_out", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("cache_hit", sa.Boolean(), nullable=False,
                  server_default=sa.false()),
        sa.Column("module", sa.String(length=60), nullable=True),
        sa.Column("template", sa.String(length=80), nullable=True),
        sa.Column("trigger_kind", sa.String(length=20), nullable=False,
                  server_default="desconocido"),
        sa.Column("trigger_detail", sa.String(length=160), nullable=False,
                  server_default="desconocido"),
        sa.Column("user_id", sa.String(), nullable=True),
        sa.Column("detail", sa.JSON(), nullable=True),
    )
    op.create_index("ix_llm_calls_purpose", "llm_calls", ["purpose"])
    # Los dos usos reales: «gasto por disparador en un rango» y «gasto por módulo».
    op.create_index("ix_llm_calls_created_trigger", "llm_calls",
                    ["created_at", "trigger_detail"])
    op.create_index("ix_llm_calls_created_module", "llm_calls",
                    ["created_at", "module"])


def downgrade() -> None:
    op.drop_index("ix_llm_calls_created_module", table_name="llm_calls")
    op.drop_index("ix_llm_calls_created_trigger", table_name="llm_calls")
    op.drop_index("ix_llm_calls_purpose", table_name="llm_calls")
    op.drop_table("llm_calls")
