"""Tourism Intel — API endpoints.

prefix: /api/v1/tourism-intel
"""
import logging
from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from shared.auth.dependencies import get_current_user
from shared.auth.models import User
from shared.database.session import get_db
from modules.tourism_intel.service import get_latest

logger = logging.getLogger("sdq.api.tourism_intel")

router = APIRouter()


def _score_payload(s) -> Dict[str, Any]:
    bd = s.breakdown or {}
    return {
        "has_score": True, "period": s.period, "itt_score": s.itt_score, "band": s.band,
        "coverage": s.coverage, "nonresident": s.nonresident, "foreign": s.foreign,
        "dimensions": bd.get("dimensions", {}), "total_demand": bd.get("total_demand", {}),
        "foreign_demand": bd.get("foreign_demand", {}), "recovery": bd.get("recovery", {}),
        "diversification": bd.get("diversification", {}), "levels": bd.get("levels", {}),
        "model_version": s.model_version, "source": "ONE",
    }


@router.get("/score", summary="Último ITT (tracción turística del destino RD)")
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
    summary="Perspectiva de IA de la tracción turística (ITT) — fase 2, lento",
    description="Narrativa que explica el ITT: demanda total, demanda extranjera, "
    "recuperación y diversificación de mercados (dato real ONE).",
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
    from modules.tourism_intel.ai_context import tourism_ai_context

    s = get_latest(db, period)
    if s is None:
        return {"has_score": False, "period": period, "ai_insight": None}
    bd = s.breakdown or {}
    index = {"itt_score": s.itt_score, "band": s.band, "coverage": s.coverage,
             "dimensions": bd.get("dimensions", {}), "total_demand": bd.get("total_demand", {}),
             "foreign_demand": bd.get("foreign_demand", {}), "recovery": bd.get("recovery", {}),
             "diversification": bd.get("diversification", {}), "levels": bd.get("levels", {})}
    ai = None
    try:
        from shared.narrative.claude_engine import narrative_engine
        res = await narrative_engine.generate(
            tourism_ai_context(index, s.period), template="tourism_outlook",
            mode="deep" if deep else "detailed", axis="tourism_intel", audience=audience)
        ai = {"text": res.text, "model_used": res.model_used, "from_cache": res.from_cache}
    except Exception as e:  # noqa: BLE001 — AI es best-effort, nunca rompe el endpoint
        logger.warning("AI insight turismo no disponible: %s", e)
    return {"has_score": True, "period": s.period, "ai_insight": ai}
