"""fix product_report_cache: unique constraint/índice deben incluir ``lang``

Revision ID: f2a4c6e8b013
Revises: b2d9f4a17c60
Create Date: 2026-07-11

Corrige un DESFASE de esquema en prod: la tabla ``product_report_cache`` (creada por
``b2d9f4a17c60``) quedó con la unique constraint SIN ``lang`` — la columna ``lang`` sí
existe (por eso ``es`` cachea), pero la constraint efectiva es (sector,tier,scope,period),
de modo que la fila ``es`` ocupa el slot y el INSERT de ``fr``/``en`` viola la constraint →
IntegrityError → rollback → esos idiomas NUNCA se cachean y se regeneran en cada descarga
(~30s). Ocurrió porque la revisión ``b2d9f4a17c60`` fue enmendada DESPUÉS de haberse
aplicado en prod: Alembic registra el id en ``alembic_version`` y no re-ejecuta una revisión
ya aplicada, así que el ``lang`` añadido a la constraint nunca llegó a la tabla viva.

Esta migración recompone la unique constraint y el índice para que incluyan ``lang``,
alineando la tabla viva con el modelo (``uq_product_report_cache_key`` /
``ix_product_report_cache_key`` sobre sector_key,tier,scope,period,lang).

Idempotente y name-agnostic en Postgres (elimina CUALQUIER unique constraint sobre la tabla
antes de crear la correcta, sin depender del nombre que tuviera la vieja). Parity
SQLite↔Postgres: en SQLite es no-op — dev recrea la tabla desde el modelo (ya con la
constraint correcta) y SQLite no soporta ALTER TABLE DROP CONSTRAINT. Aditiva: no toca datos
(las filas ``es`` cacheadas siguen válidas; ``fr``/``en`` se cachearán en la próxima descarga).
"""
from typing import Sequence, Union

from alembic import op

revision: str = "f2a4c6e8b013"
down_revision: Union[str, None] = "b2d9f4a17c60"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        # SQLite (dev): la tabla se recrea desde el modelo con la constraint correcta.
        # No hay forma de ALTER DROP CONSTRAINT y las DBs de dev son desechables.
        return

    op.execute(
        """
        DO $$
        DECLARE
            c text;
        BEGIN
            -- Defensivo: garantizar la columna (ya debería existir en prod).
            ALTER TABLE product_report_cache
                ADD COLUMN IF NOT EXISTS lang varchar(8) NOT NULL DEFAULT 'es';

            -- Eliminar TODA unique constraint viva sobre la tabla (name-agnostic):
            -- la vieja pudo quedar auto-nombrada o como uq_product_report_cache_key
            -- SIN lang. Solo hay una unique lógica en esta tabla.
            FOR c IN
                SELECT conname
                FROM pg_constraint
                WHERE conrelid = 'product_report_cache'::regclass
                  AND contype = 'u'
            LOOP
                EXECUTE 'ALTER TABLE product_report_cache DROP CONSTRAINT ' || quote_ident(c);
            END LOOP;

            -- Crear la unique constraint correcta (incluye lang).
            ALTER TABLE product_report_cache
                ADD CONSTRAINT uq_product_report_cache_key
                UNIQUE (sector_key, tier, scope, period, lang);

            -- Realinear el índice de lookup para que también incluya lang.
            DROP INDEX IF EXISTS ix_product_report_cache_key;
            CREATE INDEX ix_product_report_cache_key
                ON product_report_cache (sector_key, tier, scope, period, lang);
        END $$;
        """
    )


def downgrade() -> None:
    # No-op: revertir a una constraint SIN lang reintroduciría el bug. La forma correcta
    # (con lang) es la definida por el modelo; no hay motivo operativo para deshacerla.
    pass
