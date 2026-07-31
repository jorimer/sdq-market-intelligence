"""Canonical metric vocabulary for brand trackers.

A tracker names things its own way ("lugar favorito", "T2B de fidelidad", "incidencia
U7D"). The ingest layer maps whatever the provider ships onto these codes, so every
engine downstream speaks one language and a new client does not require new columns.

``kind`` is the load-bearing field. It decides what statistics are legitimate:
  * ``proportion``  — a % of a base. Binomial confidence bands apply.
  * ``index``       — a double-indexation score (100 = set average). Bands do NOT apply:
                      these are ratios over a normalized total, not proportions of a base.
  * ``currency``    — money. Deflatable; bands do not apply.
  * ``count``       — raw counts.

Treating an index as a proportion would manufacture confidence intervals out of nothing.
That is why ``supports_bands`` exists and why every engine consults it before scoring.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Optional


@dataclass(frozen=True)
class MetricDef:
    code: str
    label: str
    kind: str                      # proportion | index | currency | count
    is_core: bool = False          # part of the forecast/vigilance core set
    higher_is_better: bool = True
    category_denominator: bool = False
    # True when the metric can be summed across brands to build a category size.
    # Only reach-type metrics qualify: a "favourite place" share already sums to ~100
    # by construction, so summing it measures nothing.
    description: str = ""

    @property
    def supports_bands(self) -> bool:
        return self.kind == "proportion"


METRICS: List[MetricDef] = [
    MetricDef("awareness_total", "Conocimiento total", "proportion",
              description="Espontáneo + ayudado."),
    MetricDef("awareness_spontaneous", "Conocimiento espontáneo", "proportion"),
    MetricDef("awareness_tom", "Top of mind", "proportion"),
    MetricDef("ever_tried", "Consumo alguna vez", "proportion"),
    MetricDef("reach_3m", "Consumo últimos 3 meses", "proportion"),
    MetricDef("reach_1m", "Consumo último mes", "proportion"),
    MetricDef("reach_7d", "Incidencia últimos 7 días", "proportion", is_core=True,
              category_denominator=True,
              description="Penetración a 7 días. Base del denominador de categoría."),
    MetricDef("last_visit_share", "Última visita", "proportion", is_core=True),
    MetricDef("favourite_place", "Lugar favorito", "proportion", is_core=True,
              description="Preferencia declarada."),
    MetricDef("brand_opinion_t2b", "Opinión de marca (T2B)", "proportion", is_core=True),
    MetricDef("loyalty_t2b", "Índice de fidelidad (T2B)", "proportion", is_core=True),
    MetricDef("satisfaction_t2b", "Satisfacción última visita (T2B)", "proportion", is_core=True),
    MetricDef("delivery_t2b", "Evaluación de delivery (T2B)", "proportion"),
    MetricDef("ticket_avg", "Ticket promedio", "currency",
              description="Gasto medio por visita, estimado o declarado."),
    MetricDef("attribute_index", "Índice de atributo", "index",
              description="Doble indexación; 100 = promedio del set. Sin banda."),
]

_BY_CODE: Dict[str, MetricDef] = {m.code: m for m in METRICS}

# Funnel ladder, in order. Used by the funnel engine to compute step conversion.
FUNNEL_LADDER: List[str] = [
    "awareness_total", "ever_tried", "reach_3m", "reach_1m", "reach_7d",
]


def get_metric(code: str) -> Optional[MetricDef]:
    return _BY_CODE.get(code)


def core_metrics() -> List[MetricDef]:
    """The indicators that get a frozen forecast and a vigilance threshold each wave."""
    return [m for m in METRICS if m.is_core]


def label_for(code: str) -> str:
    m = _BY_CODE.get(code)
    return m.label if m else code


def supports_bands(code: str) -> bool:
    m = _BY_CODE.get(code)
    return bool(m and m.supports_bands)
