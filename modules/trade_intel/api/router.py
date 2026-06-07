"""Trade Intel — API endpoints.

prefix: /api/v1/trade-intel
"""
import logging
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Body, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from shared.auth.dependencies import get_current_user
from shared.auth.models import User
from shared.database.session import get_db
from modules.trade_intel.scoring.concentration import compute_trade_scores
from modules.trade_intel.service import (
    compute_and_persist,
    get_flows,
    get_latest_score,
)

logger = logging.getLogger("sdq.api.trade_intel")

router = APIRouter()

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
    summary="Calcular, persistir y publicar el score comercial",
    description="Persiste los flujos y el score del período y publica 'trade.updated'.",
)
async def snapshot(
    payload: Dict[str, Any] = Body(
        ..., examples=[{"period": "2025", "flows": _EXAMPLE_FLOWS}]
    ),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> Dict[str, Any]:
    period = payload.get("period")
    flows = payload.get("flows")
    if not period or not isinstance(flows, list) or not flows:
        raise HTTPException(status_code=400, detail="Se requiere 'period' y 'flows'.")
    try:
        return compute_and_persist(db, period=period, flows=flows)
    except (ValueError, KeyError) as e:
        raise HTTPException(status_code=400, detail=str(e))


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
    return {
        "has_score": True,
        "period": s.period,
        "hhi_exports": s.hhi_exports,
        "export_diversification": s.export_diversification,
        "import_dependency": s.import_dependency,
        "resilience_score": s.resilience_score,
        "model_version": s.model_version,
    }
