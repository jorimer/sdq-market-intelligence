"""Agrega 'revision_anual' al tipo reporttype.

La Revisión Anual es un tipo de informe nuevo y `reports.report_type` es un ENUM. Se sigue al
pie el precedente de `1b6970e7d069` (el que agregó 'anuario'), que a su vez salió de la
lección de `d1c8e4b90735`: aquella declaró un `CREATE TYPE` dentro de un `create_table`, pasó
en CI —SQLite, sin namespace global que colisionar— y tumbó el deploy en Postgres. El
contenedor corre `alembic upgrade head` ANTES de levantar el servidor, así que una migración
rota es un healthcheck fallido, no un error tardío.

En Postgres los tipos viven en un namespace GLOBAL y el valor se agrega con `ALTER TYPE`; en
SQLite un Enum de SQLAlchemy es un VARCHAR con un CHECK por tabla, así que el `ALTER TYPE` no
existe y no hace falta. Por eso se bifurca por dialecto.

`ADD VALUE IF NOT EXISTS` la hace idempotente. El downgrade NO quita el valor: Postgres no
soporta quitar etiquetas de un enum, y fingir que sí dejaría un downgrade que miente.

Revision ID: 7c4a2e91b0d3
Revises: 1b6970e7d069
"""
from alembic import op

revision = "7c4a2e91b0d3"
down_revision = "1b6970e7d069"
branch_labels = None
depends_on = None


def upgrade() -> None:
    if op.get_bind().dialect.name == "postgresql":
        # Fuera de transacción: en Postgres el valor nuevo de un enum no puede USARSE en la
        # misma transacción que lo agrega.
        with op.get_context().autocommit_block():
            op.execute("ALTER TYPE reporttype ADD VALUE IF NOT EXISTS 'revision_anual'")


def downgrade() -> None:
    # Postgres no permite quitar una etiqueta de un enum. Se deja constancia en vez de
    # simular un downgrade que no revierte nada.
    pass
