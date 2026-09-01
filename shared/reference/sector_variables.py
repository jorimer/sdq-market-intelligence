"""El panel de variables sectoriales del país — una fila por (sector, dimensión, variable, período).

**Por qué vive en `shared/reference/` y no en `sector_intel`.** Adentro no hay nada de un eje:
son cuatro registros NACIONALES que el país publica sobre su propia economía —el valor
agregado por sector de las cuentas nacionales del BCRD, los ocupados por rama de la ENCFT,
el panel estructural de la ENAE y los flujos de inversión extranjera directa por actividad—.
`sector_intel` es el primer consumidor, no el dueño; el perfil sectorial de `shared/` es el
segundo, y los once ejes que lo leen van detrás.

Lo mudó la decisión del 2026-09-01, que cerró la pregunta que la fase 3 del plan
(`docs/PLAN_ENRIQUECIMIENTO_SECTORIAL.md`) dejó abierta: la alternativa era que `shared/`
importara el modelo de un módulo, que es la excepción que la fase 1 evitó mudando el cubo de
crédito en vez de leerlo desde afuera.

**El nombre de la tabla NO cambia.** `si_variables` se conserva con su prefijo de módulo
aunque el modelo ya no viva ahí: el nombre es un contrato con la base, y renombrarlo exigiría
una migración de datos para ganar únicamente estética. El prefijo es historia, no dueño.
"""
from sqlalchemy import Column, Date, Float, Index, String

from shared.database.base import Base, UUIDMixin

# ── Las cuatro RESOLUCIONES que conviven en la tabla ──────────────────────────
# Viven acá, con el modelo, y no en el sync que las escribe: son parte de la llave, y
# `SECTOR_DIMENSION` llegó a estar declarado DOS veces (el sync y el servicio) con el
# mismo literal — dos declaraciones de la misma llave es cómo una se queda atrás.
#: Los 17 slugs del BCRD (valor agregado de las cuentas nacionales). Es la resolución del
#: índice sectorial: las otras tres dimensiones NO son insumos del IAI, y por eso tampoco
#: definen su grilla de períodos.
SECTOR_DIMENSION = "sector"
#: Las 10 ramas de actividad de la ENCFT (ONE). NO son los 17 slugs: son el desenlace del
#: Gate E (Δempleo) y el insumo crudo del que se deriva `labor_availability` por slug.
LABOR_ENCFT_DIMENSION = "labor_encft"
#: Los 9 sectores de la Encuesta Nacional de Actividad Económica (ONE) — un corte parcial,
#: no los 17. De acá sale la rentabilidad estructural.
ENAE_DIMENSION = "enae"
#: Las 9 actividades del cuadro de IED del BCRD, tercera resolución del mismo mapa. Es el
#: desenlace de inversión del Gate E, no un insumo del índice.
IED_DIMENSION = "ied_bcrd"


class SectorVariable(UUIDMixin, Base):
    """Un valor crudo por (sector, dimensión, variable, período), con su procedencia.

    **`dimension` es lo que separa RESOLUCIONES distintas del mismo mapa**, y por eso hay
    que leerla siempre junto a `sector_code`: `sector` va por los 17 slugs del BCRD,
    `labor_encft` por las 10 ramas de la ENCFT, `enae` por los 9 sectores de la encuesta e
    `ied_bcrd` por las 9 actividades del cuadro de inversión. Son cuatro llaves distintas
    conviviendo en una columna, y quien filtre por `sector_code` sin filtrar por `dimension`
    va a mezclar poblaciones que la fuente nunca unió. El puente entre las cuatro es
    `shared/data/sector_crosswalk.py`.

    `value` nulo significa AUSENTE y jamás se interpola: la brecha se declara.
    """
    __tablename__ = "si_variables"
    __table_args__ = (
        Index("ix_si_var_sector_period", "sector_code", "period"),
    )

    sector_code = Column(String(40), nullable=False)
    dimension = Column(String(40), nullable=False)
    variable = Column(String(60), nullable=False)
    value = Column(Float, nullable=True)               # NULL = missing, no interpolation
    period = Column(String(10), nullable=True)
    source = Column(String(40), nullable=True)
    published_at = Column(Date, nullable=True)
    license = Column(String(120), nullable=True)
