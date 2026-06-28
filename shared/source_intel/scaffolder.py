"""Andamiaje de integración (Increment 4 de la Capa 3).

Para una sugerencia (idealmente aprobada), genera un PLAN de integración concreto para
ESTE codebase: cómo acceder al dato, qué conector escribir, a qué dimensión/gate mapea,
los pasos, riesgos y esfuerzo. Es una PROPUESTA — el build real lo ejecuta el dueño/dev
(doctrina: el sistema propone, el dueño dispone; aceptar+integrar es decisión humana).

Usa Claude; sin API key o si no parsea, cae a un plan HEURÍSTICO honesto (``method``).
NO escribe ni despliega código — solo el plan.
"""
from __future__ import annotations

import json
import logging
from typing import Any, Dict

from sqlalchemy.orm import Session

from shared.config.settings import settings

logger = logging.getLogger("sdq.source_intel.scaffolder")

_SYSTEM = (
    "Eres un ingeniero de datos del equipo de SDQ·MIP (plataforma FastAPI + SQLAlchemy, "
    "conectores en shared/data/ con httpx, operaciones agendables en shared.operations, "
    "índices por eje en modules/{eje}/). Dada una fuente/sector a integrar, produces un "
    "PLAN de integración concreto y realista para ESTE codebase. No escribes código; "
    "describes el andamiaje. Respondes SOLO con un objeto JSON, sin texto alrededor."
)


def _heuristic(suggestion: Dict[str, Any], reason: str) -> Dict[str, Any]:
    axis = suggestion.get("target_axis") or "el eje objetivo"
    return {
        "data_access": "Por determinar (investigar API/descarga/scraping de la fuente).",
        "connector": f"Nuevo conector en shared/data/ (patrón httpx + UA), wired a {axis}.",
        "crosswalk": "Mapear la fuente a la dimensión/variable de la brecha.",
        "target": f"{axis} · {suggestion.get('target_gate') or 'gate por confirmar'}",
        "steps": ["Confirmar acceso y formato del dato",
                  "Escribir el conector + parser",
                  "Cablear a la dimensión/índice del eje",
                  "Operación agendable + tests + verificar en prod"],
        "risks": ["Acceso/licencia de la fuente sin confirmar",
                  "Granularidad puede no calzar con la dimensión"],
        "effort": "por estimar",
        "method": f"heuristic ({reason})",
    }


def _coerce(raw: Dict[str, Any], suggestion: Dict[str, Any]) -> Dict[str, Any]:
    def _strlist(v: Any) -> list:
        if isinstance(v, list):
            return [str(x)[:300] for x in v][:8]
        return [str(v)[:300]] if v else []
    return {
        "data_access": str(raw.get("data_access") or "")[:600],
        "connector": str(raw.get("connector") or "")[:600],
        "crosswalk": str(raw.get("crosswalk") or "")[:600],
        "target": str(raw.get("target") or
                      f"{suggestion.get('target_axis') or '—'} · {suggestion.get('target_gate') or '—'}")[:200],
        "steps": _strlist(raw.get("steps")),
        "risks": _strlist(raw.get("risks")),
        "effort": str(raw.get("effort") or "por estimar")[:120],
        "method": "ai",
    }


def scaffold_plan(db: Session, suggestion: Dict[str, Any]) -> Dict[str, Any]:
    """Genera el plan de integración para *suggestion* (dict serializado)."""
    api_key = getattr(settings, "ANTHROPIC_API_KEY", None)
    if not api_key:
        return _heuristic(suggestion, "sin API key")
    try:
        import anthropic
    except ImportError:
        return _heuristic(suggestion, "paquete anthropic ausente")

    ev = suggestion.get("evaluation") or {}
    user = (
        f"Sugerencia: tipo={suggestion.get('kind')}, título={suggestion.get('title')!r}, "
        f"descripción={suggestion.get('description') or '—'!r}, "
        f"eje={suggestion.get('target_axis') or '—'}, gate={suggestion.get('target_gate') or '—'}.\n"
        f"Evaluación previa: score={ev.get('score')}, gate_closed={ev.get('gate_closed')}, "
        f"rationale={ev.get('fit_rationale') or '—'}.\n\n"
        "Devuelve SOLO este JSON con el plan de integración para el codebase SDQ·MIP: "
        "{\"data_access\": \"cómo se accede el dato (API/descarga/scraping, formato)\", "
        "\"connector\": \"qué conector escribir y dónde (shared/data/, patrón httpx)\", "
        "\"crosswalk\": \"a qué dimensión/variable del índice del eje mapea\", "
        "\"target\": \"eje · gate que cierra\", "
        "\"steps\": [\"paso 1\", \"paso 2\", ...], "
        "\"risks\": [\"riesgo 1\", ...], \"effort\": \"estimación (S/M/L o días)\"}."
    )
    try:
        client = anthropic.Anthropic(api_key=api_key)
        # 2500: un plan rico (conector + crosswalk + pasos + riesgos) supera 1100 tokens y
        # se truncaba → JSON inválido → siempre caía a heurística (visto en prod). Holgura.
        resp = client.messages.create(
            model=settings.ANTHROPIC_MODEL, max_tokens=2500,
            system=_SYSTEM, messages=[{"role": "user", "content": user}])
        text = resp.content[0].text.strip()
        if text.startswith("```"):
            text = text.strip("`")
            text = text[text.find("{"):]
        text = text[text.find("{"): text.rfind("}") + 1]
        return _coerce(json.loads(text), suggestion)
    except Exception as e:  # noqa: BLE001 — cualquier fallo IA → heurística, no romper
        logger.warning("andamiaje IA falló (%s); usando heurística", e)
        return _heuristic(suggestion, "respuesta IA no parseable")
