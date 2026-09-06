"""Agrega 'boletin_regional' al tipo reporttype.

El boletín se registró en sus treinta superficies —enum de Python, endpoint, plantillas,
secciones, presupuesto de tokens, etiquetas del PDF, cuatro mapas del frontend, tres archivos
de i18n— y faltó la única que vive en la BASE. `anuario` y `revision_anual` tuvieron cada una
su migración; esta no se escribió.

El síntoma: `POST /boletin-regional/generate` devuelve 500 en 0,38 segundos, antes de llamar
al modelo. Python acepta el miembro del enum y PostgreSQL rechaza el INSERT. **En SQLite un
Enum de SQLAlchemy es un VARCHAR con un CHECK por tabla**, así que la batería entera pasa en
verde y el informe no puede existir en producción.

Mismo patrón que `1b6970e7d069`, que ya resolvió esto para `anuario`: `ADD VALUE IF NOT
EXISTS` dentro de un `autocommit_block` —en Postgres un valor nuevo de enum no puede USARSE en
la misma transacción que lo agrega— y sin downgrade que finja revertir, porque Postgres no
permite quitar etiquetas de un enum.

Revision ID: e2b8d0c5a731
Revises: e1a7c9d4b620
"""
from alembic import op

revision = "e2b8d0c5a731"
down_revision = "e1a7c9d4b620"
branch_labels = None
depends_on = None


def upgrade() -> None:
    if op.get_bind().dialect.name == "postgresql":
        with op.get_context().autocommit_block():
            op.execute("ALTER TYPE reporttype ADD VALUE IF NOT EXISTS 'boletin_regional'")


def downgrade() -> None:
    # Postgres no permite quitar una etiqueta de un enum. Se deja constancia en vez de
    # simular un downgrade que no revierte nada.
    pass
