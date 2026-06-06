"""Sector Intel — API endpoints.

prefix: /api/v1/sector-intel
"""
import logging
from typing import Any, Dict

from fastapi import APIRouter, Body, Depends, HTTPException
from sqlalchemy.orm import Session

from shared.auth.dependencies import get_current_user
from shared.auth.models import User
from shared.database.session import get_db
from modules.sector_intel.scoring.iai import IAI_CONFIG, compute_iai
from modules.sector_intel.scoring.sgps import (
    W_ACCELERATION,
    W_HISTORICAL,
    W_STRUCTURAL,
)
from modules.sector_intel.service import (
    compute_and_persist,
    get_latest,
    get_sectors,
    seed_sectors,
)

logger = logging.getLogger("sdq.api.sector_intel")

router = APIRouter()

_EXAMPLE_DATASET = {
    "turismo": {"gdp_growth": 5.0, "inflation_stability": 70, "ease_of_business": 65,
                "operating_cost": 40, "labor_availability": 75, "skills_index": 60,
                "regulatory_quality": 62, "regulatory_volatility": 30,
                "sector_growth": 8.0, "sector_size": 70},
    "energia": {"gdp_growth": 4.0, "inflation_stability": 68, "ease_of_business": 55,
                "operating_cost": 60, "labor_availability": 50, "skills_index": 65,
                "regulatory_quality": 58, "regulatory_volatility": 45,
                "sector_growth": 6.0, "sector_size": 60},
}


@router.get("/weights", summary="Pesos del IAI (doctrina)")
async def weights(current_user: User = Depends(get_current_user)) -> Dict[str, Any]:
    return {
        "iai_dimension_weights": IAI_CONFIG.dimension_weights,
        "iai_dimension_variables": IAI_CONFIG.dimension_variables,
        "iai_risk_increasing": sorted(IAI_CONFIG.risk_increasing),
        "sgps_weights": {
            "historical": W_HISTORICAL,
            "structural": W_STRUCTURAL,
            "acceleration": W_ACCELERATION,
        },
        "direction": IAI_CONFIG.direction,
    }


@router.get("/sectors", summary="Sectores en alcance")
async def sectors(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> Dict[str, Any]:
    seed_sectors(db)
    rows = get_sectors(db)
    return {
        "sectors": [{"code": s.code, "name": s.name, "is_active": s.is_active} for s in rows],
        "count": len(rows),
    }


@router.post("/iai", summary="Calcular IAI (sin persistir)")
async def iai(
    payload: Dict[str, Any] = Body(..., example={"sector_code": "turismo", "dataset": _EXAMPLE_DATASET}),
    current_user: User = Depends(get_current_user),
) -> Dict[str, Any]:
    sector_code = payload.get("sector_code")
    dataset = payload.get("dataset")
    if not sector_code or not isinstance(dataset, dict):
        raise HTTPException(status_code=400, detail="Se requiere 'sector_code' y 'dataset'.")
    try:
        return compute_iai(sector_code, dataset)
    except KeyError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.post(
    "/snapshot",
    summary="Calcular IAI+SGPS por sector, persistir y publicar 'sector.updated'",
    description="SGPS combina histórico/estructural/aceleración (esta última desde macro/irmp/trade).",
)
async def snapshot(
    payload: Dict[str, Any] = Body(
        ...,
        example={
            "period": "2025",
            "dataset": _EXAMPLE_DATASET,
            "sgps_inputs": {
                "turismo": {"historical": 75, "structural": 80},
                "energia": {"historical": 60, "structural": 70},
            },
        },
    ),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> Dict[str, Any]:
    period = payload.get("period")
    dataset = payload.get("dataset")
    if not period or not isinstance(dataset, dict) or not dataset:
        raise HTTPException(status_code=400, detail="Se requiere 'period' y 'dataset'.")
    try:
        return compute_and_persist(
            db, period=period, sector_dataset=dataset,
            sgps_inputs=payload.get("sgps_inputs"),
            country_code=payload.get("country_code", "DO"),
        )
    except (ValueError, KeyError) as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/{sector_code}/latest", summary="Último IAI/SGPS persistido de un sector")
async def latest(
    sector_code: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> Dict[str, Any]:
    s = get_latest(db, sector_code)
    if s is None:
        return {"has_score": False, "sector_code": sector_code}
    return {
        "has_score": True,
        "sector_code": sector_code,
        "period": s.period,
        "iai_score": s.iai_score,
        "iai_band": s.iai_band,
        "sgps_score": s.sgps_score,
        "iai_breakdown": s.iai_breakdown,
        "sgps_breakdown": s.sgps_breakdown,
        "model_version": s.model_version,
    }
