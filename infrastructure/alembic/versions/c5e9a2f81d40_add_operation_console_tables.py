"""add operation_runs + operation_schedules (Consola de Operación)

Las operaciones recurrentes (rescore, prune-future, recompute-carteras, …) eran
curl-only. Estas tablas respaldan la consola en la UI: historial de corridas para
auditoría y cronogramas durables para el scheduler in-app (el next-run vive en la
DB, así que sobrevive reinicios).

Revision ID: c5e9a2f81d40
Revises: a3d8f1b6c52e
Create Date: 2026-06-15
"""
from alembic import op
import sqlalchemy as sa

revision = "c5e9a2f81d40"
down_revision = "a3d8f1b6c52e"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "operation_runs",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("operation", sa.String(length=50), nullable=False),
        sa.Column("origin", sa.String(length=20), nullable=False),
        sa.Column("triggered_by", sa.String(), nullable=True),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("started_at", sa.DateTime(), nullable=True),
        sa.Column("finished_at", sa.DateTime(), nullable=True),
        sa.Column("summary", sa.JSON(), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["triggered_by"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_operation_runs_operation", "operation_runs", ["operation"])
    op.create_index("ix_operation_runs_created", "operation_runs", ["created_at"])

    op.create_table(
        "operation_schedules",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("operation", sa.String(length=50), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column("interval_hours", sa.Integer(), nullable=False),
        sa.Column("params", sa.JSON(), nullable=True),
        sa.Column("next_run_at", sa.DateTime(), nullable=True),
        sa.Column("last_run_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("operation"),
    )
    op.create_index("ix_operation_schedules_operation", "operation_schedules", ["operation"])


def downgrade() -> None:
    op.drop_index("ix_operation_schedules_operation", table_name="operation_schedules")
    op.drop_table("operation_schedules")
    op.drop_index("ix_operation_runs_created", table_name="operation_runs")
    op.drop_index("ix_operation_runs_operation", table_name="operation_runs")
    op.drop_table("operation_runs")
