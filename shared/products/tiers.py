"""Niveles de producto (Pulse / Insight / Deep Dive) — constantes en todos los sectores.

Framework sector-agnóstico: vive en ``shared/`` como el Cerebro de Insights
(``shared/narrative``). Define el vocabulario de niveles y la especificación
declarativa de un nivel. NO conoce ningún sector — los sectores se declaran vía
``SectorProductManifest`` (ver ``manifest.py``) e implementan el ``Protocol``
``SectorProduct`` (ver ``contract.py``).
"""
from __future__ import annotations

import enum
from dataclasses import dataclass
from typing import Optional, Tuple


class ProductTier(str, enum.Enum):
    """Los tres niveles comerciales de profundidad."""

    pulse = "pulse"          # sistema, sin nombrar (bandas) — periódico/abierto
    insight = "insight"      # entidad/segmento nombrado — recurrente
    deep_dive = "deep_dive"  # a medida — on-demand


class Granularity(str, enum.Enum):
    """Granularidad de un nivel. ``system`` NUNCA emite nombres de entidad."""

    system = "system"            # agregado anonimizado (Pulse)
    named_entity = "named_entity"  # entidad nombrada (Insight / Deep Dive)


@dataclass(frozen=True)
class TierLevelSpec:
    """Definición declarativa de un nivel para un sector (config-as-code).

    Es la única fuente de verdad de qué lleva un nivel: secciones, granularidad,
    templates de narrativa, marca y metadato comercial. Agregar/quitar una sección
    = editar el manifiesto, nunca el motor de render.

    Campos tupla (no list) para que el dataclass sea inmutable y hashable.
    """

    tier: ProductTier
    granularity: Granularity
    sections: Tuple[str, ...]              # claves de sección, en orden de render
    narrative_templates: Tuple[str, ...]   # templates SCQA esperados (señal G3)
    audience: str                          # metadato comercial
    cadence: str                           # "periodic" | "recurring" | "on_demand"
    watermark: Optional[str] = None        # p.ej. "Vista abierta · SDQMIP"
    base_report_type: Optional[str] = None  # pista opcional para el render del sector
    price_band: Optional[str] = None       # metadato comercial (NO lógica de billing)

    def __post_init__(self) -> None:
        # Doctrina no negociable: Pulse jamás nombra entidades.
        if self.tier == ProductTier.pulse and self.granularity != Granularity.system:
            raise ValueError(
                "Pulse debe ser de granularidad 'system' (anonimizado); "
                f"se recibió '{self.granularity.value}'."
            )
