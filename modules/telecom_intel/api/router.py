"""Telecom Intel — API endpoints.

prefix: /api/v1/telecom-intel
"""
import logging
from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from shared.auth.dependencies import get_current_user
from shared.auth.models import User
from shared.database.session import get_db
from modules.telecom_intel.service import get_latest

logger = logging.getLogger("sdq.api.telecom_intel")

router = APIRouter()


@router.get("/score", summary="Último IDT (desarrollo telecom)")
async def latest_score(
    period: Optional[str] = Query(None),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> Dict[str, Any]:
    s = get_latest(db, period)
    if s is None:
        return {"has_score": False, "period": period}
    bd = s.breakdown or {}
    # La fuente se infiere del período: con "Q" = boletín INDOTEL (trimestral, congelado
    # en 2022-Q1, histórico); sin "Q" = ITU DataHub (anual, fuente vigente). Igual criterio
    # que ``telecom_intel.products`` para no re-etiquetar como INDOTEL un dato ya migrado.
    source = "INDOTEL (histórico)" if "Q" in (s.period or "") else "ITU DataHub"
    return {
        "has_score": True, "period": s.period, "telecom_score": s.telecom_score,
        "band": s.band, "coverage": s.coverage,
        "mobile_penetration": s.mobile_penetration,
        "internet_penetration": s.internet_penetration,
        "broadband_share": s.broadband_share,
        "dimensions": bd.get("dimensions", {}), "metrics": bd.get("metrics", {}),
        "model_version": s.model_version, "source": source,
    }


@router.get(
    "/insight",
    summary="Perspectiva de IA del desarrollo telecom (IDT) — fase 2, lento (~10-15s)",
    description="Narrativa que explica el IDT: penetración móvil/internet y calidad "
    "de banda ancha (dato real INDOTEL).",
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
    from modules.telecom_intel.ai_context import telecom_ai_context

    s = get_latest(db, period)
    if s is None:
        return {"has_score": False, "period": period, "ai_insight": None}
    bd = s.breakdown or {}
    index = {"telecom_score": s.telecom_score, "band": s.band, "coverage": s.coverage,
             "dimensions": bd.get("dimensions", {}), "metrics": bd.get("metrics", {})}
    ai = None
    try:
        from shared.narrative.claude_engine import narrative_engine
        res = await narrative_engine.generate(
            telecom_ai_context(index, s.period), template="telecom_outlook",
            mode="deep" if deep else "detailed", axis="telecom_intel", audience=audience)
        ai = {"text": res.text, "model_used": res.model_used, "from_cache": res.from_cache}
    except Exception as e:  # noqa: BLE001 — AI best-effort, nunca rompe el endpoint
        logger.warning("AI insight telecom no disponible: %s", e)
    return {"has_score": True, "period": s.period, "ai_insight": ai}
