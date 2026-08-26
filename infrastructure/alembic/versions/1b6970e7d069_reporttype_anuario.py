"""Agrega 'anuario' al tipo reporttype.

El anuario del sistema es un tipo de informe nuevo y `reports.report_type` es un ENUM. En
Postgres los tipos viven en un namespace GLOBAL y el valor se agrega con `ALTER TYPE`; en
SQLite —donde corre el job de migraciones de CI— un Enum de SQLAlchemy es un VARCHAR con un
CHECK por tabla, así que el `ALTER TYPE` no existe y no hace falta: la restricción se recrea
sola cuando la tabla se crea de cero, y una base de dev existente acepta el valor nuevo salvo
que el CHECK lo liste (recrearlo pediría reconstruir la tabla, y no vale la pena para dev).

Por eso se bifurca por dialecto, como manda la lección de `d1c8e4b90735`: aquella migración
declaró un `CREATE TYPE` dentro de un `create_table`, pasó en CI (SQLite, sin namespace que
colisionar) y tumbó el deploy en Postgres. El contenedor corre `alembic upgrade head` ANTES de
levantar el servidor: una migración rota es un healthcheck fallido, no un error tardío.

`ADD VALUE IF NOT EXISTS` la hace idempotente. El downgrade NO quita el valor: Postgres no
soporta quitar etiquetas de un enum, y fingir que sí dejaría un downgrade que miente.

Revision ID: 1b6970e7d069
Revises: b8d1f36c07a4
"""
from alembic import op

revision = "1b6970e7d069"
down_revision = "b8d1f36c07a4"
branch_labels = None
depends_on = None


def upgrade() -> None:
    if op.get_bind().dialect.name == "postgresql":
        # Fuera de transacción: en Postgres el valor nuevo de un enum no puede USARSE en la
        # misma transacción que lo agrega. Acá solo se agrega, pero el autocommit evita
        # sorpresas si la migración se encadena con otra que inserte.
        with op.get_context().autocommit_block():
            op.execute("ALTER TYPE reporttype ADD VALUE IF NOT EXISTS 'anuario'")


def downgrade() -> None:
    # Postgres no permite quitar una etiqueta de un enum. Se deja constancia en vez de
    # simular un downgrade que no revierte nada.
    pass
