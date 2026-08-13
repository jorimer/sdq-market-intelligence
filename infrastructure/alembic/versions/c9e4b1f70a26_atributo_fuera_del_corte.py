"""Saca los atributos del campo CORTE en las observaciones ya confirmadas.

El índice de atributo se mide POR atributo, y hasta hoy el modelo no tenía dónde guardarlo.
Quien llenó la plantilla del proveedor hizo lo único posible: lo puso en `segment`. Así, el
expediente de McDonald's tiene «Tiene pollo delicioso» y «Es una marca en la que confío»
conviviendo con «Santo Domingo» como si fueran poblaciones.

Consecuencias que esto arrastra: toda lectura por plaza mezcla cortes reales con enunciados,
y la planilla de pedido al proveedor —que deriva de estas observaciones— le pediría a Ipsos
que vuelva a poner un atributo donde va una plaza, institucionalizando el error.

ALCANCE, deliberadamente estrecho. Solo `attribute_index`, y solo cuando el corte NO es una
población conocida. En el expediente real esa métrica tiene 21 cortes distintos y los 21 son
atributos: cero ambigüedad. Las demás métricas no se tocan — `reach_7d` usa
`categoria_qsr`/`categoria_food_service`, que SON agrupaciones legítimas y no atributos.

REVERSIBILIDAD. La bajada devuelve el atributo al corte, que es exactamente el estado
anterior. Reversible de verdad, no de palabra: ninguna fila pierde información en el camino.

Revision ID: c9e4b1f70a26
Revises: b8d3f5a2c704
"""
import sqlalchemy as sa
from alembic import op

revision = "c9e4b1f70a26"
down_revision = "b8d3f5a2c704"
branch_labels = None
depends_on = None

#: Poblaciones legítimas. Un corte que esté acá NO es un atributo, aunque la métrica se mida
#: por atributo: la lista se declara en vez de deducirse, porque adivinar cuál de dos
#: dimensiones es cuál sobre datos ya confirmados de un cliente no admite heurísticas.
_POBLACIONES = (
    "total", "Santiago", "Santo Domingo", "santiago", "santo domingo",
    "bc+", "c/c-", "d", "categoria_qsr", "categoria_food_service",
    "15 - 18", "19 - 24", "25 - 34", "35 - 49", "50 - 65",
)


def upgrade() -> None:
    conn = op.get_bind()
    marcadores = ", ".join(f":p{i}" for i in range(len(_POBLACIONES)))
    params = {f"p{i}": v for i, v in enumerate(_POBLACIONES)}

    antes = conn.execute(sa.text(
        f"SELECT COUNT(*) FROM brand_observations WHERE metric_code = 'attribute_index' "
        f"AND (attribute IS NULL OR attribute = '') AND segment NOT IN ({marcadores})"
    ), params).scalar()

    conn.execute(sa.text(
        f"UPDATE brand_observations SET attribute = segment, segment = 'total' "
        f"WHERE metric_code = 'attribute_index' "
        f"AND (attribute IS NULL OR attribute = '') AND segment NOT IN ({marcadores})"
    ), params)

    # La misma cirugía sobre las lecturas: son el registro de qué dijo cada entrega, y si
    # quedan con el atributo en el corte, la próxima promoción reintroduce el defecto.
    conn.execute(sa.text(
        f"UPDATE brand_observation_readings SET attribute = segment, segment = 'total' "
        f"WHERE metric_code = 'attribute_index' "
        f"AND (attribute IS NULL OR attribute = '') AND segment NOT IN ({marcadores})"
    ), params)

    print(f"[atributo-fuera-del-corte] observaciones movidas: {antes}")


def downgrade() -> None:
    conn = op.get_bind()
    for tabla in ("brand_observations", "brand_observation_readings"):
        conn.execute(sa.text(
            f"UPDATE {tabla} SET segment = attribute, attribute = NULL "
            f"WHERE metric_code = 'attribute_index' "
            f"AND attribute IS NOT NULL AND attribute != ''"
        ))
