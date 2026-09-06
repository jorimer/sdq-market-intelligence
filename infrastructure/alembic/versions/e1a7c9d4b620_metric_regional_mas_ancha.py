"""Ensancha `rb_country_aggregates.metric`: SECMCA genera claves de hasta 104 caracteres.

La columna se declaró `String(60)` y el sync de SECMCA lleva un día fallando en producción con
`value too long for type character varying(60)`. Treinta de sus sesenta y cinco claves
distintas pasan el límite: la clave es `<cuadro>::<etiqueta de columna>` y las etiquetas del
emisor son frases enteras («Saldos vivos (tasa promedio ponderada) · Acuerdos de recompra 2/ ·
Plazo · Mas de un año», 104 caracteres).

**Por qué no lo vio la batería.** SQLite NO aplica el largo de un `VARCHAR(n)`: acepta la
cadena entera y sigue. PostgreSQL la rechaza. Los 8.666 tests corren sobre SQLite y pasaban en
verde contra este defecto. Lo mismo pasó, el mismo día, con un valor de enum ausente (ver
`e2b8d0c5a731`): es una clase entera de restricciones sobre la que los tests son ciegos, y por
eso este arreglo viene con guards estructurales que sí corren en SQLite.

No se trunca la clave: `metric` es parte de la clave única `(iso, corte, métrica, fuente)`, así
que acortarla no perdería un nombre largo sino que COLAPSARÍA dos series distintas en una.

En SQLite es un no-op a propósito. El `ALTER COLUMN` obliga a reconstruir la tabla y no hay
nada que arreglar: el largo nunca se aplicó. Misma bifurcación por dialecto que en
`1b6970e7d069`, y por la misma lección: una migración que asume Postgres pasa en CI y tumba el
deploy.

Revision ID: e1a7c9d4b620
Revises: a4c8e1b70d93
"""
import sqlalchemy as sa
from alembic import op

revision = "e1a7c9d4b620"
down_revision = "a4c8e1b70d93"
branch_labels = None
depends_on = None


def upgrade() -> None:
    if op.get_bind().dialect.name == "postgresql":
        op.alter_column("rb_country_aggregates", "metric",
                        existing_type=sa.String(60), type_=sa.String(200),
                        existing_nullable=False)


def downgrade() -> None:
    # Volver a 60 rompería las filas que este arreglo permite guardar. El downgrade deja la
    # columna ancha en vez de destruir dato: una reversión que pierde filas no es reversible.
    pass
