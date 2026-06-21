"""Transversal tools endpoints (cross-axis utilities).

prefix: /api/v1/tools

These endpoints carry NO module coupling: the comparador insight receives the
already-computed items (axis label + each item's score + dimension breakdown) in
the request body and only asks the narrative engine for a comparative reading. It
never touches any module's DB/models, so it stays purely transversal.
"""
import json
import logging
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Body, Depends, HTTPException
from sqlalchemy.orm import Session

from shared.auth.dependencies import get_current_user
from shared.auth.models import User
from shared.database.session import get_db
from shared.settings.models import AppSetting

logger = logging.getLogger("sdq.api.tools")

router = APIRouter()

# KV key escrito por la Operación market-brief (app/market_brief.py). Se hardcodea
# para no importar app/ desde shared/ (dirección de dependencia: app → shared).
MARKET_BRIEF_KEY = "market_brief_report"


async def _ai_insight(context: Dict[str, Any], template: str) -> Optional[Dict[str, Any]]:
    """Best-effort Claude narrative (returns None on any failure so the endpoint
    never breaks)."""
    try:
        from shared.narrative.claude_engine import narrative_engine
        res = await narrative_engine.generate(context, template=template, mode="detailed")
        return {"text": res.text, "model_used": res.model_used, "from_cache": res.from_cache}
    except Exception as e:  # noqa: BLE001
        logger.warning("compare insight no disponible: %s", e)
        return None


@router.post(
    "/compare-insight",
    summary="Insight comparativo cross-eje (IA)",
    description="Análisis comparativo SCQA de 2–4 elementos de cualquier eje. Recibe "
    "los scores y desgloses ya calculados; no recalcula nada.",
)
async def compare_insight(
    body: Dict[str, Any] = Body(
        ...,
        examples=[{
            "eje": "Sectorial — IAI",
            "items": [
                {"nombre": "Turismo", "score": 72.4, "banda": "Sólido",
                 "dimensiones": {"Macroeconómica": 68, "Sector": 80}},
                {"nombre": "Construcción", "score": 55.1, "banda": "Vigilar",
                 "dimensiones": {"Macroeconómica": 60, "Sector": 50}},
            ],
        }],
    ),
    current_user: User = Depends(get_current_user),
) -> Dict[str, Any]:
    eje = body.get("eje")
    items = body.get("items")
    if not isinstance(items, list) or len(items) < 2:
        raise HTTPException(status_code=400, detail="Se requieren al menos 2 elementos para comparar.")

    clean: List[Dict[str, Any]] = []
    for it in items[:4]:
        if not isinstance(it, dict):
            continue
        clean.append({
            "nombre": str(it.get("nombre") or it.get("label") or "—"),
            "score": it.get("score"),
            "banda": it.get("banda"),
            "dimensiones": it.get("dimensiones") if isinstance(it.get("dimensiones"), dict) else {},
        })
    if len(clean) < 2:
        raise HTTPException(status_code=400, detail="Se requieren al menos 2 elementos válidos.")

    ctx = {"eje": str(eje) if eje else "comparación", "elementos": clean}
    ai = await _ai_insight(ctx, "cross_compare")
    return {"eje": eje, "items": [c["nombre"] for c in clean], "ai_insight": ai}


@router.get(
    "/market-brief",
    summary="Market Brief cacheado (síntesis cross-eje de RD)",
    description="Lee el último brief persistido (snapshot de los 7 ejes + narrativa IA). "
    "Lo genera/agenda la Operación «market-brief» en la Consola de Operación.",
)
async def market_brief(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> Dict[str, Any]:
    row = db.query(AppSetting).filter(AppSetting.key == MARKET_BRIEF_KEY).first()
    if not row or not row.value:
        return {"computed": False,
                "message": "Aún no se ha generado el Market Brief. Genéralo con «Regenerar»."}
    return {"computed": True, **json.loads(row.value)}
