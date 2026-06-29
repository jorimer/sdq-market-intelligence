"""Energy Intel — API endpoints.

prefix: /api/v1/energy-intel
"""
import logging
from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from shared.auth.dependencies import get_current_user
from shared.auth.models import User
from shared.database.session import get_db
from modules.energy_intel.service import get_latest

logger = logging.getLogger("sdq.api.energy_intel")

router = APIRouter()


def _score_payload(s) -> Dict[str, Any]:
    bd = s.breakdown or {}
    return {
        "has_score": True, "period": s.period, "energy_score": s.energy_score,
        "band": s.band, "coverage": s.coverage, "capacity_mw": s.capacity_mw,
        "capacity_score": s.capacity_score, "service_score": s.service_score,
        "transition_score": s.transition_score,
        "dimensions": bd.get("dimensions", {}), "capacity": bd.get("capacity", {}),
        "service": bd.get("service", {}), "transition": bd.get("transition", {}),
        "model_version": s.model_version, "source": "SIE + ONE",
    }


@router.get("/score", summary="Último IRSE (resiliencia del sector eléctrico)")
async def latest_score(
    period: Optional[str] = Query(None),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> Dict[str, Any]:
    s = get_latest(db, period)
    if s is None:
        return {"has_score": False, "period": period}
    return _score_payload(s)


@router.get(
    "/insight",
    summary="Perspectiva de IA de la resiliencia eléctrica (IRSE) — fase 2, lento (~10-15s)",
    description="Narrativa que explica el IRSE: adecuación de capacidad y calidad de "
    "servicio (SIE) y transición renovable de la matriz (ONE) — las 3 dimensiones con "
    "dato real.",
)
async def insight(
    period: Optional[str] = Query(None),
    audience: str = Query("inversionista",
                          description="inversionista·gobierno·empresa·multilateral; "
                                      "clave desconocida cae al default."),
    deep: bool = Query(False, description="Versión extendida (análisis completo)."),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> Dict[str, Any]:
    from modules.energy_intel.ai_context import energy_ai_context

    s = get_latest(db, period)
    if s is None:
        return {"has_score": False, "period": period, "ai_insight": None}
    bd = s.breakdown or {}
    index = {"energy_score": s.energy_score, "band": s.band, "coverage": s.coverage,
             "dimensions": bd.get("dimensions", {}), "capacity": bd.get("capacity", {}),
             "service": bd.get("service", {}), "transition": bd.get("transition", {})}
    ai = None
    try:
        from shared.narrative.claude_engine import narrative_engine
        res = await narrative_engine.generate(
            energy_ai_context(index, s.period), template="energy_outlook",
            mode="deep" if deep else "detailed", axis="energy_intel", audience=audience)
        ai = {"text": res.text, "model_used": res.model_used, "from_cache": res.from_cache}
    except Exception as e:  # noqa: BLE001 — AI es best-effort, nunca rompe el endpoint
        logger.warning("AI insight energía no disponible: %s", e)
    return {"has_score": True, "period": s.period, "ai_insight": ai}
