"""Social Development — API endpoints.

prefix: /api/v1/social-dev
"""
import logging
from typing import Any, Dict, Optional

from fastapi import APIRouter, Body, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from shared.auth.dependencies import get_current_user
from shared.auth.models import User
from shared.database.session import get_db
from modules.social_dev.scoring.development import IDM_CONFIG
from modules.social_dev.service import (
    compute_and_persist,
    get_latest,
    get_scores,
)

logger = logging.getLogger("sdq.api.social_dev")

router = APIRouter()

_EXAMPLE = {
    "period": "2025",
    "dataset": {
        "nacional": {"life_expectancy": 74, "child_mortality": 28, "literacy_rate": 94,
                     "schooling_years": 9, "income_per_capita": 9000, "poverty_rate": 23,
                     "financial_inclusion": 56, "informality_rate": 55},
        "santo_domingo": {"life_expectancy": 76, "child_mortality": 22, "literacy_rate": 96,
                          "schooling_years": 11, "income_per_capita": 12000, "poverty_rate": 18,
                          "financial_inclusion": 65, "informality_rate": 48},
    },
}


@router.get("/weights", summary="Pesos del índice de desarrollo (doctrina)")
async def weights(current_user: User = Depends(get_current_user)) -> Dict[str, Any]:
    return {
        "dimension_weights": IDM_CONFIG.dimension_weights,
        "dimension_variables": IDM_CONFIG.dimension_variables,
        "risk_increasing": sorted(IDM_CONFIG.risk_increasing),
        "direction": IDM_CONFIG.direction,
    }


@router.post(
    "/index",
    summary="Calcular, persistir y publicar el índice de desarrollo",
    description="Índice multidimensional por entidad (región/grupo) con distribución; publica 'social.updated'.",
)
async def index(
    payload: Dict[str, Any] = Body(..., examples=[_EXAMPLE]),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> Dict[str, Any]:
    period = payload.get("period")
    dataset = payload.get("dataset")
    if not period or not isinstance(dataset, dict) or not dataset:
        raise HTTPException(status_code=400, detail="Se requiere 'period' y 'dataset'.")
    try:
        return compute_and_persist(db, period=period, dataset=dataset)
    except (ValueError, KeyError) as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/indicators", summary="Scores de desarrollo persistidos")
async def indicators(
    period: Optional[str] = Query(None),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> Dict[str, Any]:
    rows = get_scores(db, period)
    items = [
        {"entity_key": r.entity_key, "period": r.period,
         "development_score": r.development_score, "band": r.band}
        for r in rows
    ]
    return {"indicators": items, "count": len(items)}


@router.get("/sdg", summary="Resumen ODS (placeholder estructurado)")
async def sdg(
    entity_key: str = Query("nacional"),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> Dict[str, Any]:
    s = get_latest(db, entity_key)
    if s is None:
        return {"has_score": False, "entity_key": entity_key}
    # Map the development dimensions to broad SDG groupings (explainable summary).
    return {
        "has_score": True,
        "entity_key": entity_key,
        "period": s.period,
        "development_score": s.development_score,
        "band": s.band,
        "dimensions": s.breakdown,
    }
