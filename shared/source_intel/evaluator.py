"""Evaluación IA de una sugerencia (Increment 2 de la Capa 3).

Puntúa una sugerencia de fuente/información/sector contra los criterios de aceptación y
la mapea a la brecha real del readiness del eje. Usa Claude (``ANTHROPIC_MODEL``) para el
juicio cualitativo; si no hay API key o la respuesta no parsea, cae a una evaluación
HEURÍSTICA honesta (``method="heuristic"``) — nunca inventa un veredicto seguro.

Honestidad declarada: la evaluación es por conocimiento del modelo + criterios, NO
verificación web en vivo (no hay web search cableado). El campo ``method`` lo expone.
"""
from __future__ import annotations

import json
import logging
from typing import Any, Dict, Optional

from sqlalchemy.orm import Session

from shared.config.settings import settings

logger = logging.getLogger("sdq.source_intel.evaluator")

_CRITERIA = ("coverage", "cadence", "format", "license")
_RECS = ("approve", "investigate", "reject", "defer")

# Criterios de aceptación de una fuente nueva (espejan el brief de investigación).
_CRITERIA_DOC = (
    "coverage: ¿el dato es por sector/entidad (no solo agregado nacional), o real-con-"
    "fallback honesto? · cadence: ¿cadencia y frescura conocidas? · format: ¿estructurado "
    "(Excel/CSV/API) mejor que PDF/OCR? · license: ¿público o licenciable, con cita?"
)

_SYSTEM = (
    "Eres un evaluador de fuentes de datos para una plataforma de inteligencia de mercado "
    "de República Dominicana. Evalúas si una sugerencia (una fuente, un tipo de información, "
    "o un sector nuevo) ayuda a cerrar una brecha concreta de cobertura/validación. Eres "
    "realista y honesto: si no conoces la fuente o dudas que exista/sea usable, lo dices y "
    "bajas el score. NO verificas en web; juzgas por conocimiento y por los criterios. "
    "Respondes SOLO con un objeto JSON válido, sin texto alrededor."
)


def _gap_context(db: Session, axis: Optional[str]) -> str:
    """Linaje de la brecha del eje (desde el Readiness Audit) para anclar la evaluación."""
    if not axis:
        return "Sin eje objetivo (p.ej. propuesta de sector nuevo): evalúa el encaje general."
    try:
        from shared.products.audit import build_audit
        audit = build_audit(db)
        for s in audit.get("sectors", []):
            if s.get("sector_key") == axis:
                gaps = "; ".join(
                    f"{g['label']} {g['value']:.0%}: {g['falta']}" for g in s.get("gaps", []))
                return f"Eje {axis} — readiness {s.get('readiness', {})}. Brechas: {gaps or 'ninguna'}."
        return f"Eje {axis}: sin detalle de brecha disponible."
    except Exception as e:  # noqa: BLE001 — el contexto es opcional, no debe romper la eval
        logger.warning("contexto de brecha de '%s' no disponible: %s", axis, e)
        return f"Eje {axis}: contexto de brecha no disponible."


def _heuristic(suggestion: Dict[str, Any], reason: str) -> Dict[str, Any]:
    """Evaluación heurística honesta cuando no hay IA: score neutral, a investigar."""
    return {
        "score": 0.5,
        "criteria": {c: {"score": 0.5, "note": "sin evaluar (heurística)"} for c in _CRITERIA},
        "gate_closed": suggestion.get("target_gate"),
        "fit_rationale": f"Evaluación heurística ({reason}): requiere investigación manual "
                         "contra los criterios de aceptación.",
        "recommendation": "investigate",
        "method": "heuristic",
    }


def _coerce(raw: Dict[str, Any], suggestion: Dict[str, Any]) -> Dict[str, Any]:
    """Normaliza/valida el JSON del modelo a la forma esperada (defensa ante drift)."""
    def _clamp(x: Any) -> float:
        try:
            return max(0.0, min(1.0, float(x)))
        except (TypeError, ValueError):
            return 0.5
    crit_in = raw.get("criteria") or {}
    criteria = {}
    for c in _CRITERIA:
        item = crit_in.get(c) or {}
        criteria[c] = {"score": _clamp(item.get("score")),
                       "note": str(item.get("note") or "")[:300]}
    rec = raw.get("recommendation")
    if rec not in _RECS:
        rec = "investigate"
    gate = raw.get("gate_closed") or suggestion.get("target_gate")
    if gate not in ("g1", "g2", "g3", "g4", "g5", None):
        gate = suggestion.get("target_gate")
    return {
        "score": _clamp(raw.get("score")),
        "criteria": criteria,
        "gate_closed": gate,
        "fit_rationale": str(raw.get("fit_rationale") or "")[:1200],
        "recommendation": rec,
        "method": "ai",
    }


def evaluate_suggestion(db: Session, suggestion: Dict[str, Any]) -> Dict[str, Any]:
    """Evalúa una sugerencia (dict serializado). Devuelve el objeto ``evaluation``."""
    api_key = getattr(settings, "ANTHROPIC_API_KEY", None)
    if not api_key:
        return _heuristic(suggestion, "sin API key")
    try:
        import anthropic
    except ImportError:
        return _heuristic(suggestion, "paquete anthropic ausente")

    gap = _gap_context(db, suggestion.get("target_axis"))
    user = (
        f"Sugerencia: tipo={suggestion.get('kind')}, título={suggestion.get('title')!r}, "
        f"descripción={suggestion.get('description') or '—'!r}, "
        f"eje_objetivo={suggestion.get('target_axis') or '—'}, "
        f"gate_objetivo={suggestion.get('target_gate') or '—'}.\n"
        f"Contexto de la brecha: {gap}\n"
        f"Criterios de aceptación: {_CRITERIA_DOC}\n\n"
        "Devuelve SOLO este JSON: {\"score\": 0..1 (idoneidad global para cerrar la brecha), "
        "\"criteria\": {\"coverage\": {\"score\":0..1,\"note\":\"\"}, \"cadence\": {...}, "
        "\"format\": {...}, \"license\": {...}}, \"gate_closed\": \"g1\"..\"g5\" o null, "
        "\"fit_rationale\": \"por qué encaja o no con la brecha, honesto\", "
        "\"recommendation\": \"approve|investigate|reject|defer\"}."
    )
    try:
        client = anthropic.Anthropic(api_key=api_key)
        resp = client.messages.create(
            model=settings.ANTHROPIC_MODEL, max_tokens=900,
            system=_SYSTEM, messages=[{"role": "user", "content": user}])
        text = resp.content[0].text.strip()
        # Tolera fences ```json ... ```
        if text.startswith("```"):
            text = text.strip("`")
            text = text[text.find("{"):]
        text = text[text.find("{"): text.rfind("}") + 1]
        raw = json.loads(text)
        return _coerce(raw, suggestion)
    except Exception as e:  # noqa: BLE001 — cualquier fallo IA → heurística, no romper
        logger.warning("evaluación IA falló (%s); usando heurística", e)
        return _heuristic(suggestion, "respuesta IA no parseable")
