"""Modelo del pasaje recuperable — la unidad que el retrieval devuelve con procedencia.

Motor de Research Custom · Fase 3 (docs/SPEC_MOTOR_RESEARCH_CUSTOM.md §3.2).

Cada pasaje SIEMPRE lleva su lineage (fuente + licencia + referencia): la regla dura
del §4 es que el Cerebro solo redacta con procedencia adjunta. Un pasaje sin ``source``
no debería existir en el índice.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict

# Tipos de pasaje (para que el orquestador sepa qué clase de evidencia es).
KIND_DOCTRINE = "doctrine"        # doctrina versionada (pesos, rúbrica declarada)
KIND_METHODOLOGY = "methodology"  # documento de metodología/estándar propio
KIND_REGISTRY = "registry"        # señal por-variable del Data Registry (dato vivo)
KIND_BULLETIN = "bulletin"        # boletín/publicación fuente ya ingerido

# Licencias (solo corpus propio o de derechos claros — nunca web abierta scrapeada).
LICENSE_OWN = "own"               # material propio de SDQ (doctrina, metodología)
LICENSE_PUBLIC = "public"         # fuente pública con lineage (BCRD, WGI, ONE…)


@dataclass(frozen=True)
class Passage:
    """Un fragmento recuperable con su procedencia. Inmutable."""

    text: str
    source: str                       # etiqueta de lineage (fuente legible)
    kind: str                         # KIND_*
    ref: str = ""                     # referencia (ruta de archivo o clave eje/variable)
    license: str = LICENSE_OWN        # LICENSE_*
    meta: Dict[str, Any] = field(default_factory=dict)

    def as_result(self, score: float) -> Dict[str, Any]:
        """Serializa al contrato de ``retrieve`` (mantiene text/source/score + extras)."""
        return {
            "text": self.text,
            "source": self.source,
            "score": round(float(score), 4),
            "kind": self.kind,
            "ref": self.ref,
            "license": self.license,
            **({"meta": self.meta} if self.meta else {}),
        }
