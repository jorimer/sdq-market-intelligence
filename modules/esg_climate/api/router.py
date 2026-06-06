"""ESG & Climate — API endpoints.

prefix: /api/v1/esg-climate
"""
import logging
from typing import Any, Dict, Optional

from fastapi import APIRouter, Body, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from shared.auth.dependencies import get_current_user
from shared.auth.models import User
from shared.database.session import get_db
from modules.esg_climate.scoring.exposure import IRC_CONFIG, compute_exposure
from modules.esg_climate.service import (
    compute_and_persist,
    get_latest,
    get_scores,
)

logger = logging.getLogger("sdq.api.esg_climate")

router = APIRouter()

_EXAMPLE = {
    "period": "2025",
    "dataset": {
        "turismo": {"hurricane_exposure": 80, "coastal_exposure": 90, "carbon_intensity": 40,
                    "fossil_dependence": 55, "adaptation_investment": 45, "diversification": 50,
                    "disclosure_quality": 40, "emissions_targets": 35},
        "energia": {"hurricane_exposure": 50, "coastal_exposure": 40, "carbon_intensity": 85,
                    "fossil_dependence": 80, "adaptation_investment": 55, "diversification": 45,
                    "disclosure_quality": 60, "emissions_targets": 55},
    },
}


@router.get("/weights", summary="Pesos del índice ESG/clima (doctrina)")
async def weights(current_user: User = Depends(get_current_user)) -> Dict[str, Any]:
    return {
        "dimension_weights": IRC_CONFIG.dimension_weights,
        "dimension_variables": IRC_CONFIG.dimension_variables,
        "risk_increasing": sorted(IRC_CONFIG.risk_increasing),
        "direction": IRC_CONFIG.direction,
    }


@router.post(
    "/score",
    summary="Calcular, persistir y publicar la exposición ESG/clima",
    description="Exposición + materialidad por sector; publica 'esg.updated'.",
)
async def score(
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


@router.post("/exposure", summary="Calcular exposición de un sector (sin persistir)")
async def exposure_one(
    payload: Dict[str, Any] = Body(..., examples=[{"sector_key": "turismo", "dataset": _EXAMPLE["dataset"]}]),
    current_user: User = Depends(get_current_user),
) -> Dict[str, Any]:
    sector_key = payload.get("sector_key")
    dataset = payload.get("dataset")
    if not sector_key or not isinstance(dataset, dict):
        raise HTTPException(status_code=400, detail="Se requiere 'sector_key' y 'dataset'.")
    try:
        return compute_exposure(sector_key, dataset)
    except KeyError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.get("/indicators", summary="Scores ESG persistidos (más expuestos primero)")
async def indicators(
    period: Optional[str] = Query(None),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> Dict[str, Any]:
    rows = get_scores(db, period)
    items = [
        {"sector_key": r.sector_key, "period": r.period, "esg_score": r.esg_score,
         "band": r.band, "material": r.material, "materiality_level": r.materiality_level}
        for r in rows
    ]
    return {"indicators": items, "count": len(items)}


@router.get("/score", summary="Último score ESG de un sector")
async def latest(
    sector_key: str = Query("turismo"),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> Dict[str, Any]:
    s = get_latest(db, sector_key)
    if s is None:
        return {"has_score": False, "sector_key": sector_key}
    return {
        "has_score": True,
        "sector_key": sector_key,
        "period": s.period,
        "esg_score": s.esg_score,
        "band": s.band,
        "material": s.material,
        "materiality_level": s.materiality_level,
        "breakdown": s.breakdown,
        "model_version": s.model_version,
    }
