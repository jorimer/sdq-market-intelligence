"""Free Zones Intel — API endpoints.

prefix: /api/v1/free-zones-intel
"""
import logging
from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from shared.auth.dependencies import get_current_user
from shared.auth.models import User
from shared.database.session import get_db
from modules.free_zones_intel.service import get_latest

logger = logging.getLogger("sdq.api.free_zones_intel")

router = APIRouter()


def _score_payload(s) -> Dict[str, Any]:
    bd = s.breakdown or {}
    return {
        "has_score": True, "period": s.period, "fz_score": s.fz_score, "band": s.band,
        "coverage": s.coverage, "companies": s.companies, "jobs": s.jobs,
        "exports_musd": s.exports_musd, "investment_musd": s.investment_musd,
        "dimensions": bd.get("dimensions", {}), "exports": bd.get("exports", {}),
        "investment": bd.get("investment", {}), "employment": bd.get("employment", {}),
        "productivity": bd.get("productivity", {}), "levels": bd.get("levels", {}),
        "model_version": s.model_version, "source": "CNZFE",
    }


@router.get("/score", summary="Último IZF (atractividad del sector zonas francas)")
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
    summary="Perspectiva de IA de la atractividad de zonas francas (IZF) — fase 2, lento",
    description="Narrativa que explica el IZF: dinamismo exportador, inversión, empleo y "
    "productividad (dato real CNZFE).",
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
    from modules.free_zones_intel.ai_context import free_zones_ai_context

    s = get_latest(db, period)
    if s is None:
        return {"has_score": False, "period": period, "ai_insight": None}
    bd = s.breakdown or {}
    index = {"fz_score": s.fz_score, "band": s.band, "coverage": s.coverage,
             "dimensions": bd.get("dimensions", {}), "exports": bd.get("exports", {}),
             "investment": bd.get("investment", {}), "employment": bd.get("employment", {}),
             "productivity": bd.get("productivity", {}), "levels": bd.get("levels", {})}
    ai = None
    try:
        from shared.narrative.claude_engine import narrative_engine
        res = await narrative_engine.generate(
            free_zones_ai_context(index, s.period), template="free_zones_outlook",
            mode="deep" if deep else "detailed", axis="free_zones_intel", audience=audience)
        ai = {"text": res.text, "model_used": res.model_used, "from_cache": res.from_cache}
    except Exception as e:  # noqa: BLE001 — AI es best-effort, nunca rompe el endpoint
        logger.warning("AI insight zonas francas no disponible: %s", e)
    return {"has_score": True, "period": s.period, "ai_insight": ai}
