"""add reports.file_blob to persist PDF bytes in DB

Los PDFs se escribían a ``./data/reports`` en el FS efímero del contenedor (el
servicio de la app no tiene volumen en Railway), así que tras cualquier redeploy
los archivos desaparecían y la re-descarga daba 404 aunque la fila siguiera en DB.
Esta columna guarda los bytes del PDF en Postgres, el único store durable.

Revision ID: f7a1c9d2e4b6
Revises: e4b8d6c2a1f3
Create Date: 2026-06-14
"""
from alembic import op
import sqlalchemy as sa

revision = "f7a1c9d2e4b6"
down_revision = "e4b8d6c2a1f3"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("reports", sa.Column("file_blob", sa.LargeBinary(), nullable=True))


def downgrade() -> None:
    op.drop_column("reports", "file_blob")
