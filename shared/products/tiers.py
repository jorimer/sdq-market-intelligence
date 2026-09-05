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
    #: El nivel produce su prosa **computándola**, no generándola con el motor de IA.
    #:
    #: G3 preguntaba «¿declara templates?», y la pregunta que quiere hacer es «¿este nivel
    #: tiene con qué producir su prosa?». Para dieciséis ejes las dos coinciden. Para un
    #: informe cuyo contenido son cifras de error, coberturas empíricas de intervalos y una
    #: reconciliación exacta, NO: ahí la prosa se computa, y eso es una garantía más fuerte
    #: que generarla —un modelo redactándola inventaría los números que el informe existe
    #: para probar—. Sin este campo, elegir el camino más riguroso costaba el gate.
    #:
    #: Se DECLARA y no se infiere: un nivel que no declara templates ni prosa computada
    #: sigue puntuando 0, que es el caso de «todavía no está hecho».
    prosa_computada: bool = False

    def __post_init__(self) -> None:
        # Un nivel tiene que poder producir su prosa de ALGUNA de las dos formas. Declarar
        # las dos es contradictorio: o la escribe el motor o la computa el código.
        if self.narrative_templates and self.prosa_computada:
            raise ValueError(
                "un nivel declara templates de narrativa Y prosa computada: son dos formas "
                "excluyentes de producir el texto, y tener las dos deja sin definir cuál "
                "manda.")
        # Doctrina no negociable: Pulse jamás nombra entidades.
        if self.tier == ProductTier.pulse and self.granularity != Granularity.system:
            raise ValueError(
                "Pulse debe ser de granularidad 'system' (anonimizado); "
                f"se recibió '{self.granularity.value}'."
            )
