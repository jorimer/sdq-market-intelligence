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
from modules.social_dev.scoring.development import IDM_CONFIG, distribution_stats
from modules.social_dev.service import (
    assemble_idm_dataset,
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


@router.get("/indicators", summary="Scores de desarrollo persistidos (último período)")
async def indicators(
    period: Optional[str] = Query(None, description="Período; por defecto, el último con scores."),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> Dict[str, Any]:
    rows = get_scores(db, period)
    if period is None and rows:
        from modules.social_dev.service import _period_key

        latest = max((r.period for r in rows), key=_period_key)
        rows = [r for r in rows if r.period == latest]
    items = [
        {"entity_key": r.entity_key, "period": r.period, "development_score": r.development_score,
         "band": r.band, "breakdown": r.breakdown}
        for r in rows
    ]
    dist = distribution_stats([r.development_score for r in rows if r.development_score is not None])
    return {"indicators": items, "count": len(items), "distribution": dist,
            "period": items[0]["period"] if items else None}


@router.get(
    "/dataset",
    summary="Dataset ensamblado del IDM (real + rúbrica) con procedencia",
    description=(
        "El dataset por región que alimenta el IDM: dato real (pobreza ONE por "
        "región, salud WDI nacional) + rúbrica declarada (ingreso/educación/"
        "inclusión). Incluye 'sources' (live|rubric) por variable para el badge "
        "real-vs-rúbrica. Single-source: el snapshot y la UI puntúan lo mismo."
    ),
)
async def dataset(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> Dict[str, Any]:
    return assemble_idm_dataset(db)


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
