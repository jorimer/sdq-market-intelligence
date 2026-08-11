"""rating_tier pasa a NULLABLE — la notación de letras deja de calcularse (§9)

El histórico conserva sus letras como LINAJE del dato; las filas nuevas ya no las llevan.
Seguir calculando un símbolo que nadie publica ni consume sería exactamente la "notación
muerta conviviendo dentro del sistema" que la Fase 4 vino a eliminar.

No se borra ningún valor: la columna se relaja, no se limpia.

Revision ID: b7c4e1a9d302
Revises: a3f7d2e9c145
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "b7c4e1a9d302"
down_revision: Union[str, None] = "a3f7d2e9c145"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _es_sqlite() -> bool:
    return op.get_bind().dialect.name == "sqlite"


def upgrade() -> None:
    # SQLite no soporta ALTER COLUMN; su motor no aplica NOT NULL de forma comparable y el
    # CI corre sobre SQLite, así que allí es un no-op deliberado.
    if _es_sqlite():
        return
    op.alter_column("rating_results", "rating_tier",
                    existing_type=sa.String(10), nullable=True)
    op.alter_column("rating_actions", "new_tier",
                    existing_type=sa.String(10), nullable=True)


def downgrade() -> None:
    if _es_sqlite():
        return
    # Volver a NOT NULL exige que no queden nulos: se rellenan con un marcador explícito
    # en vez de fabricar una letra, que sería inventar una calificación.
    op.execute("UPDATE rating_results SET rating_tier = 'N/D' WHERE rating_tier IS NULL")
    op.execute("UPDATE rating_actions SET new_tier = 'N/D' WHERE new_tier IS NULL")
    op.alter_column("rating_results", "rating_tier",
                    existing_type=sa.String(10), nullable=False)
    op.alter_column("rating_actions", "new_tier",
                    existing_type=sa.String(10), nullable=False)
