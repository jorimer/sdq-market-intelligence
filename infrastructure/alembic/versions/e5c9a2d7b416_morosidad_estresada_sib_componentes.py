"""La morosidad estresada OFICIAL de la SIB, con sus componentes, en banking_data.

Feedback de un alto funcionario de Banco Múltiple Santa Cruz (2026-09-15): la mora
convencional no es la comparable entre entidades; la ampliada o estresada sí, porque incluye
castigos y otros componentes. La SIB la define en su catálogo de indicadores (I.027):

    (vencida + cobranza + TC 31-60 + reestructurados REA + reestructurados temporales
     + castigos 12m + adjudicaciones 12m) / cartera

y publica cada componente en `indicadores/morosidad-estresada`, el endpoint que ya se consumía
para `castigos_pct`. Solo se guardaban los castigos.

Cada columna es un % adimensional calculado desde UNA fila de ese endpoint (componente /
`carteraTotal`), igual que `castigos_pct`: unit-safe y sin mezclar la cartera de otro endpoint
—la mora convencional sale de otra cartera y no suma con éstas—. Los castigos reusan
`castigos_pct`. La estresada NO entra al score (decisión del dueño: mora y castigos ya están;
sumarla contaría dos veces el mismo hecho). Se sirve al texto del informe.

Revision ID: e5c9a2d7b416
Revises: d4b8f2a6c913
Create Date: 2026-09-15
"""
import sqlalchemy as sa
from alembic import op

revision = "e5c9a2d7b416"
down_revision = "d4b8f2a6c913"
branch_labels = None
depends_on = None

_COLUMNS = [
    "morosidad_estresada_pct",
    "estresada_vencido_pct",
    "estresada_cobranza_pct",
    "estresada_tc31a60_pct",
    "estresada_reestructurado_rea_pct",
    "estresada_reestructurado_temporal_pct",
    "estresada_adjudicado_pct",
]


def upgrade() -> None:
    for col in _COLUMNS:
        op.add_column("banking_data", sa.Column(col, sa.Numeric(10, 4), nullable=True))


def downgrade() -> None:
    for col in _COLUMNS:
        op.drop_column("banking_data", col)
