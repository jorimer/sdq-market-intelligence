"""brand_intel: planes del cliente como documentos + metas, y ledger con medida externa

Los planes que el cliente comparte (la estrategia de su agencia, su plan de medios) solo
entraban al sistema si un analista los transcribía a mano, decisión por decisión, y solo
para métricas del tracker. Dos tablas nuevas les dan puerta: el documento con su capa de
texto (el recibo maestro) y las metas que el lector extrae de él, pendientes de adopción
humana — el lector propone, solo una persona adopta.

El ledger, además, deja de exigir métrica del tracker: la mitad de un plan real (redes,
dato transaccional) vive fuera de la encuesta. ``metric_code`` pasa a nullable y entra
``external_measure`` — la medida es una XOR la otra, validado en el borde del API. Las
metas externas nunca tocan la aritmética muestral: quedan visibles con su fuente en vez
de fingir un veredicto.

Revision ID: c4d8e2f7a961
Revises: b7e2c9f4a153
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "c4d8e2f7a961"
down_revision: Union[str, None] = "b7e2c9f4a153"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "brand_plan_documents",
        sa.Column("engagement_id", sa.String(), nullable=False),
        sa.Column("filename", sa.String(length=300), nullable=False),
        sa.Column("title", sa.String(length=300), nullable=True),
        sa.Column("source_org", sa.String(length=200), nullable=True),
        sa.Column("uploaded_by", sa.String(length=120), nullable=True),
        sa.Column("page_count", sa.Integer(), nullable=True),
        sa.Column("raw_text", sa.Text(), nullable=True),
        sa.Column("status", sa.String(length=20), nullable=False,
                  server_default="propuesto"),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("CURRENT_TIMESTAMP"),
                  nullable=False),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.text("CURRENT_TIMESTAMP"),
                  nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_brand_plan_document_engagement", "brand_plan_documents",
                    ["engagement_id", "status"])

    op.create_table(
        "brand_plan_goals",
        sa.Column("engagement_id", sa.String(), nullable=False),
        sa.Column("plan_document_id", sa.String(), nullable=False),
        sa.Column("claim", sa.Text(), nullable=False),
        sa.Column("page_number", sa.Integer(), nullable=True),
        sa.Column("kind", sa.String(length=20), nullable=False, server_default="meta"),
        sa.Column("metric_code", sa.String(length=60), nullable=True),
        sa.Column("segment", sa.String(length=60), nullable=False, server_default="total"),
        sa.Column("target_from", sa.Float(), nullable=True),
        sa.Column("target_to", sa.Float(), nullable=True),
        sa.Column("expected_move", sa.Float(), nullable=True),
        sa.Column("owner_declared", sa.String(length=200), nullable=True),
        sa.Column("measure_source", sa.String(length=200), nullable=True),
        sa.Column("confident", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("status", sa.String(length=20), nullable=False,
                  server_default="propuesta"),
        sa.Column("adopted_decision_id", sa.String(), nullable=True),
        sa.Column("dismiss_note", sa.Text(), nullable=True),
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("CURRENT_TIMESTAMP"),
                  nullable=False),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.text("CURRENT_TIMESTAMP"),
                  nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_brand_plan_goal_engagement", "brand_plan_goals",
                    ["engagement_id", "status"])

    # SQLite no altera columnas en sitio: batch mode recrea la tabla (no-op en Postgres,
    # que sí ejecuta el ALTER directo). Patrón ya usado en el módulo.
    with op.batch_alter_table("brand_decisions") as batch:
        batch.alter_column("metric_code", existing_type=sa.String(length=60),
                           nullable=True)
        batch.add_column(sa.Column("external_measure", sa.Text(), nullable=True))


def downgrade() -> None:
    # El downgrade exige que ninguna fila use lo nuevo: una decisión externa no puede
    # volverse NOT NULL sin inventarle una métrica — mejor fallar ruidoso que corromper.
    with op.batch_alter_table("brand_decisions") as batch:
        batch.drop_column("external_measure")
        batch.alter_column("metric_code", existing_type=sa.String(length=60),
                           nullable=False)
    op.drop_index("ix_brand_plan_goal_engagement", table_name="brand_plan_goals")
    op.drop_table("brand_plan_goals")
    op.drop_index("ix_brand_plan_document_engagement", table_name="brand_plan_documents")
    op.drop_table("brand_plan_documents")
