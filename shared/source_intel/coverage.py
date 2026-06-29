"""Detección de cobertura — ¿la brecha de una sugerencia ya está cubierta?

Una sugerencia de fuente para un eje cuyo gate de DATOS (g1) ya está en pleno es
redundante: la fuente autoritativa ya está integrada (p.ej. telecom resuelto vía ITU,
energy tras cerrar la transición). El sistema lo MARCA y auto-difiere para que el tablero
se auto-limpie, sin que el dueño tenga que rechazar a mano las que envejecen (como pasó
con los boletines INDOTEL, propuestos antes de que ITU cerrara la brecha).

Reusa el Readiness Audit (``build_audit``) — la misma verdad que el monitor de activación.
Doctrina: el sistema propone (difiere, reversible); el dueño dispone (el rechazo final).

CONSERVADOR a propósito: marca cubierto SOLO cuando g1 (datos autoritativos) está en
pleno. NO marca sectores con g1 parcial (construction/free_zones/tourism aún con variables
en rúbrica → sus fuentes sí ayudan) ni propuestas de sector nuevo (sin eje objetivo).
"""
from __future__ import annotations

import logging
from typing import Any, Dict, Optional

from sqlalchemy.orm import Session

logger = logging.getLogger("sdq.source_intel.coverage")


def coverage_status(db: Session, axis: Optional[str]) -> Dict[str, Any]:
    """``{covered: bool, note: str}`` — ¿el eje *axis* ya tiene g1 (datos) en pleno?

    ``covered=True`` solo cuando el sector está implementado y NO tiene brecha abierta en
    g1. Best-effort: cualquier fallo del audit devuelve ``covered=False`` (no marca de más,
    no rompe la evaluación)."""
    if not axis:
        return {"covered": False, "note": ""}
    try:
        from shared.products.audit import build_audit
        audit = build_audit(db)
    except Exception as e:  # noqa: BLE001 — el audit es best-effort, nunca romper
        logger.warning("coverage_status: audit no disponible: %s", e)
        return {"covered": False, "note": ""}
    sec = next((s for s in audit.get("sectors", []) if s.get("sector_key") == axis), None)
    if not sec or not sec.get("implemented"):
        return {"covered": False, "note": ""}
    g1_open = any(g.get("gate") == "g1" for g in sec.get("gaps", []))
    if g1_open:
        return {"covered": False, "note": ""}
    name = sec.get("display_name", axis)
    return {
        "covered": True,
        "note": (f"{axis}/g1 (datos) ya en cobertura plena — {name} publicable; "
                 f"fuente redundante."),
    }
