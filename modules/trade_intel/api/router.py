"""Trade Intel — API endpoints.

prefix: /api/v1/trade-intel
"""
import logging
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Body, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from shared.auth.dependencies import get_current_user, require_role
from shared.auth.models import User, UserRole
from shared.database.session import get_db
from modules.trade_intel.models.models import TradeFlow, TradeScore
from modules.trade_intel.scoring.concentration import compute_trade_scores
from modules.trade_intel.service import (
    compute_and_persist,
    get_flows,
    get_latest_score,
)

logger = logging.getLogger("sdq.api.trade_intel")

router = APIRouter()


async def _ai_insight(context: Dict[str, Any], template: str) -> Dict[str, Any] | None:
    """Generate a Claude narrative from *context*; best-effort (returns None on any
    failure so the endpoint never breaks). Without an API key the engine returns a
    static fallback (``model_used == "static_fallback"``), passed through."""
    try:
        from shared.narrative.claude_engine import narrative_engine
        res = await narrative_engine.generate(context, template=template, mode="detailed")
        return {"text": res.text, "model_used": res.model_used, "from_cache": res.from_cache}
    except Exception as e:  # noqa: BLE001 — AI is best-effort, never break the endpoint
        logger.warning("AI insight comercio (%s) no disponible: %s", template, e)
        return None

_EXAMPLE_FLOWS = [
    {"product": "ferroníquel", "direction": "export", "value": 1200.0, "partner": "US"},
    {"product": "instrumentos médicos", "direction": "export", "value": 2100.0, "partner": "US"},
    {"product": "cigarros", "direction": "export", "value": 900.0, "partner": "EU"},
    {"product": "petróleo", "direction": "import", "value": 3800.0, "partner": "US"},
]


@router.post(
    "/score",
    summary="Calcular score de resiliencia comercial (sin persistir)",
    description="HHI de exportaciones, diversificación, dependencia de importaciones y resiliencia.",
)
async def score(
    payload: Dict[str, Any] = Body(..., examples=[{"flows": _EXAMPLE_FLOWS}]),
    current_user: User = Depends(get_current_user),
) -> Dict[str, Any]:
    flows = payload.get("flows")
    if not isinstance(flows, list) or not flows:
        raise HTTPException(status_code=400, detail="Se requiere 'flows' (lista no vacía).")
    return compute_trade_scores(flows)


@router.post(
    "/snapshot",
    summary="Calcular, persistir y publicar el score comercial (admin)",
    description="Persiste los flujos y el score del período y publica 'trade.updated'. "
    "Solo admin: es el contrato de ingesta real (DGA/aduanas), no una vía para "
    "sembrar datos desde la UI.",
)
async def snapshot(
    payload: Dict[str, Any] = Body(
        ..., examples=[{"period": "2025", "flows": _EXAMPLE_FLOWS}]
    ),
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role(UserRole.admin)),
) -> Dict[str, Any]:
    period = payload.get("period")
    flows = payload.get("flows")
    if not period or not isinstance(flows, list) or not flows:
        raise HTTPException(status_code=400, detail="Se requiere 'period' y 'flows'.")
    try:
        return compute_and_persist(db, period=period, flows=flows)
    except (ValueError, KeyError) as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.delete(
    "/data",
    summary="Purgar el dato comercial persistido (admin)",
    description="Borra todos los flujos y scores comerciales persistidos. Para "
    "limpiar fixture ilustrativo: no hay fuente real (DGA sin licencia) hasta "
    "habilitar aduanas.",
)
async def purge_data(
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role(UserRole.admin)),
) -> Dict[str, Any]:
    scores = db.query(TradeScore).delete()
    flows = db.query(TradeFlow).delete()
    db.commit()
    logger.info("Purgado dato comercial: %d scores, %d flujos", scores, flows)
    return {"scores_deleted": scores, "flows_deleted": flows}


@router.get("/flows", summary="Flujos comerciales persistidos")
async def flows(
    period: Optional[str] = Query(None),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> Dict[str, Any]:
    rows = get_flows(db, period)
    items: List[Dict[str, Any]] = [
        {
            "product": r.product,
            "direction": r.direction.value,
            "value": r.value,
            "period": r.period,
            "partner": r.partner,
        }
        for r in rows
    ]
    return {"flows": items, "count": len(items), "period": period}


@router.get("/concentration", summary="Concentración de exportaciones (HHI)")
async def concentration(
    period: Optional[str] = Query(None),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> Dict[str, Any]:
    s = get_latest_score(db, period)
    if s is None:
        return {"has_score": False, "period": period}
    breakdown = s.breakdown or {}
    return {
        "has_score": True,
        "period": s.period,
        "hhi_exports": s.hhi_exports,
        "export_diversification": s.export_diversification,
        "top_export_products": breakdown.get("top_export_products", []),
    }


@router.get("/score", summary="Último score de resiliencia persistido")
async def latest_score(
    period: Optional[str] = Query(None),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> Dict[str, Any]:
    s = get_latest_score(db, period)
    if s is None:
        return {"has_score": False, "period": period}
    bd = s.breakdown or {}
    return {
        "has_score": True,
        "period": s.period,
        "hhi_exports": s.hhi_exports,
        "export_diversification": s.export_diversification,
        "import_dependency": s.import_dependency,
        "resilience_score": s.resilience_score,
        "model_version": s.model_version,
        # Full breakdown so the UI renders headline + treemap from one read.
        "total_exports": bd.get("total_exports"),
        "total_imports": bd.get("total_imports"),
        "n_products_export": bd.get("n_products_export"),
        "n_products_import": bd.get("n_products_import"),
        "top_export_products": bd.get("top_export_products", []),
        "source": "DGA",
    }


@router.get(
    "/insight",
    summary="Perspectiva de IA del comercio exterior (resiliencia) — fase 2, lento (~10-15s)",
    description="Narrativa SCQA que explica la resiliencia comercial: concentración "
    "exportadora por capítulo y dependencia de importaciones (datos DGA/Aduanas).",
)
async def insight(
    period: Optional[str] = Query(None),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> Dict[str, Any]:
    from modules.trade_intel.ai_context import trade_ai_context

    s = get_latest_score(db, period)
    if s is None:
        return {"has_score": False, "period": period, "ai_insight": None}
    bd = s.breakdown or {}
    score = {
        "period": s.period, "hhi_exports": s.hhi_exports,
        "export_diversification": s.export_diversification,
        "import_dependency": s.import_dependency, "resilience_score": s.resilience_score,
        "total_exports": bd.get("total_exports"), "total_imports": bd.get("total_imports"),
        "n_products_export": bd.get("n_products_export"),
        "top_export_products": bd.get("top_export_products", []),
    }
    return {"has_score": True, "period": s.period,
            "ai_insight": await _ai_insight(trade_ai_context(score), "trade_outlook")}


@router.get(
    "/validation/backtest",
    summary="Backtest de resiliencia comercial (Gate E)",
    description="Devuelve el último backtest persistido: discriminación (Gini + IC) "
    "de la resiliencia vs shocks externos realizados, en panel regional.",
)
async def get_backtest(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> Dict[str, Any]:
    from shared.settings.models import AppSetting
    import json

    row = db.query(AppSetting).filter(AppSetting.key == "trade_backtest_report").first()
    if not row:
        return {"has_report": False}
    return {"has_report": True, **json.loads(row.value)}
