"""Gate de honestidad de publicación (§3.4) — la regla dura del producto.

Un reporte custom NO sale al comprador si la fracción del cuerpo sin ancla de dato real
NI rúbrica declarada supera el umbral: en ese caso se entrega un *scoping report*
(qué se puede y no contestar hoy, y qué fuente cerraría la brecha) en vez de un informe
con apariencia de completo. Esto es lo que impide "fabricar por omisión" justo cuando
el cliente más necesita ver honestidad.
"""
from __future__ import annotations

from typing import List, Tuple

from shared.registry.signals import REAL
from shared.research.models import GATE_REPORT, GATE_SCOPING, SubQuestion

# Umbral inicial propuesto por el spec (§3.4): >40% del cuerpo sin ancla → scoping.
DEFAULT_GAP_THRESHOLD = 0.40


def evaluate_gate(sub_questions: List[SubQuestion],
                  gap_threshold: float = DEFAULT_GAP_THRESHOLD) -> Tuple[str, float, float]:
    """Devuelve ``(gate, coverage_real, anchored_fraction)``.

    - ``anchored_fraction`` = fracción de sub-preguntas con ancla (real o rúbrica).
    - ``coverage_real``     = fracción con dato REAL (el estándar más alto).
    - ``gate``              = SCOPING si la brecha (1 - anclado) supera el umbral, o si
                              no hay sub-preguntas; REPORT en caso contrario.
    """
    n = len(sub_questions)
    if n == 0:
        return GATE_SCOPING, 0.0, 0.0
    anchored = sum(1 for sq in sub_questions if sq.anchored)
    real = sum(1 for sq in sub_questions if sq.state == REAL)
    anchored_fraction = round(anchored / n, 4)
    coverage_real = round(real / n, 4)
    gap_fraction = 1.0 - anchored_fraction
    gate = GATE_SCOPING if gap_fraction > gap_threshold else GATE_REPORT
    return gate, coverage_real, anchored_fraction
