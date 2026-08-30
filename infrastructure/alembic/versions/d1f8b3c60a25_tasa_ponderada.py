"""`tasa_por_deuda` (suma cruda) → `tasa_ponderada` (la tasa, acotada).

Qué pasó. `tasaPorDeuda` del cubo de la SIB viene YA ponderado por el emisor, y su magnitud
desborda `Numeric(22,4)` incluso sumándolo sin multiplicar — o sea que su unidad no es la
que se supuso. Dos backfills murieron por eso: el primero a los 107 minutos y el segundo, ya
con escritura por trimestre, en UN minuto.

Guardar un número cuya unidad no se entiende no sirve para nada y es peor que no guardarlo:
alguien lo usaría creyendo que la entiende. Se persiste la TASA derivada —numerador sobre su
base, que sí se lee— con `deuda_con_tasa` al lado para poder re-ponderar al agregar.

`Numeric(9,4)` en vez de (22,4) porque una tasa no necesita dieciocho dígitos enteros, y una
columna que solo admite lo plausible es una defensa más. Fuera de la banda creíble el valor
es NULL: dice «no se pudo derivar», que es distinto de un cero.

La columna está VACÍA en producción — los backfills que la iban a llenar son los que
fallaron — así que el cambio de tipo no pierde ningún dato.

Revision ID: d1f8b3c60a25
Revises: c9d2e5a81f47
"""
import sqlalchemy as sa
from alembic import op

revision = "d1f8b3c60a25"
down_revision = "c9d2e5a81f47"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.drop_column("cartera_sectorial", "tasa_por_deuda")
    op.add_column("cartera_sectorial",
                  sa.Column("tasa_ponderada", sa.Numeric(9, 4), nullable=True))


def downgrade() -> None:
    op.drop_column("cartera_sectorial", "tasa_ponderada")
    op.add_column("cartera_sectorial",
                  sa.Column("tasa_por_deuda", sa.Numeric(22, 4), nullable=True))
