"""add ml_models table to persist the trained model in Postgres

El pickle del XGBoost se guardaba solo en ``MODELS_DIR`` (FS efímero del
contenedor — el servicio de la app no tiene volumen en Railway), así que tras
cada redeploy el modelo desaparecía y ``ml_available`` volvía a false. Esta tabla
persiste los bytes del modelo en Postgres; la fila más reciente es la activa.

Revision ID: a3d8f1b6c52e
Revises: f7a1c9d2e4b6
Create Date: 2026-06-14
"""
from alembic import op
import sqlalchemy as sa

revision = "a3d8f1b6c52e"
down_revision = "f7a1c9d2e4b6"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "ml_models",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("module", sa.String(length=50), nullable=False),
        sa.Column("version", sa.String(length=50), nullable=True),
        sa.Column("model_blob", sa.LargeBinary(), nullable=False),
        sa.Column("metrics", sa.JSON(), nullable=True),
        sa.Column("trained_by", sa.String(), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["trained_by"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_ml_models_module_created", "ml_models", ["module", "created_at"])


def downgrade() -> None:
    op.drop_index("ix_ml_models_module_created", table_name="ml_models")
    op.drop_table("ml_models")
