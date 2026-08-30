"""Amplía `cartera_sectorial`: tasa ponderada, desembolso, moneda, persona y clases B-E.

Por qué en una sola migración y ANTES de repoblar. Re-hacer el backfill del cubo de
créditos cuesta unas dos horas y media, y cada campo que se agregue después obliga a pagar
esa espera otra vez. Se decide el conjunto completo y se paga una vez.

Por qué MEDIDAS y no dimensiones. `moneda` y `persona` tienen dos valores cada una y
`clasificacionEntidad` seis; convertirlas en grano multiplicaría las filas por veinticuatro
para no decir nada nuevo. Como medidas, el grano sigue siendo sector × provincia.

`deuda_x_tasa` guarda Σ(tasa × deuda) y `deuda_con_tasa` su base. Así el promedio ponderado
se reconstruye a cualquier nivel de agregación; guardar una tasa ya promediada la volvería
irrecuperable, porque el promedio simple de celdas de tamaño distinto no es la tasa de nadie.

Todas las columnas son nullable: las filas ya cargadas por #997 no las tienen, y un NOT NULL
con default las llenaría de ceros — que se leerían como «no tiene», no como «no se midió».

Revision ID: b8c1e4f70d92
Revises: a3f7c2d9e451
"""
import sqlalchemy as sa
from alembic import op

revision = "b8c1e4f70d92"
down_revision = "a3f7c2d9e451"
branch_labels = None
depends_on = None

_COLUMNAS = (
    ("desembolso", sa.Numeric(18, 2)),
    ("deuda_capital", sa.Numeric(18, 2)),
    ("plasticos", sa.Numeric(18, 2)),
    ("deuda_x_tasa", sa.Numeric(22, 4)),
    ("deuda_con_tasa", sa.Numeric(18, 2)),
    ("deuda_moneda_extranjera", sa.Numeric(18, 2)),
    ("deuda_persona_fisica", sa.Numeric(18, 2)),
    ("cartera_b", sa.Numeric(18, 2)),
    ("cartera_c", sa.Numeric(18, 2)),
    ("cartera_d", sa.Numeric(18, 2)),
    ("cartera_e", sa.Numeric(18, 2)),
)


def upgrade() -> None:
    for nombre, tipo in _COLUMNAS:
        op.add_column("cartera_sectorial", sa.Column(nombre, tipo, nullable=True))


def downgrade() -> None:
    for nombre, _ in reversed(_COLUMNAS):
        op.drop_column("cartera_sectorial", nombre)
