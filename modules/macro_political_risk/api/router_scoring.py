"""Macro-Political Risk — Scoring endpoints.

prefix: /api/v1/macro-political-risk

The core scoring is DB-agnostic and deterministic: the client supplies the
regional dataset and a target country, and the engine returns a full,
auditable IRMP breakdown.  Persistence will be layered on top later.
"""
import logging
from datetime import date
from typing import Any, Dict

from fastapi import APIRouter, Body, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from shared.auth.dependencies import get_current_user
from shared.auth.models import User
from shared.database.session import get_db
from modules.macro_political_risk.scoring.engine import run_irmp
from modules.macro_political_risk.scoring.weights import (
    DIMENSION_VARIABLES,
    DIMENSION_WEIGHTS,
    RISK_INCREASING_VARIABLES,
)
from modules.macro_political_risk.service import (
    compute_and_persist,
    get_history,
    get_latest,
)

logger = logging.getLogger("sdq.api.macro_political_risk")

router = APIRouter()


@router.get(
    "/weights",
    summary="Ponderaciones y variables del IRMP",
    description="Devuelve la configuración del índice para transparencia/explicabilidad.",
)
async def get_weights() -> Dict[str, Any]:
    return {
        "dimension_weights": DIMENSION_WEIGHTS,
        "dimension_variables": DIMENSION_VARIABLES,
        "risk_increasing_variables": sorted(RISK_INCREASING_VARIABLES),
        "direction": "mayor score = menor riesgo",
    }


@router.post(
    "/score",
    summary="Calcular IRMP para un país",
    description=(
        "Calcula el Índice de Riesgo Macro-Político de un país contra el "
        "conjunto regional provisto. Determinista y auditable."
    ),
)
async def score_country(
    payload: Dict[str, Any] = Body(
        ...,
        examples=[{
            "country_code": "DO",
            "dataset": {
                "DO": {"gdp_cagr_3y": 4.5, "public_debt_gdp": 45.0},
                "CR": {"gdp_cagr_3y": 3.2, "public_debt_gdp": 63.0},
                "PA": {"gdp_cagr_3y": 5.1, "public_debt_gdp": 52.0},
            },
        }],
    ),
    current_user: User = Depends(get_current_user),
) -> Dict[str, Any]:
    country_code = payload.get("country_code")
    dataset = payload.get("dataset")
    if not country_code or not isinstance(dataset, dict):
        raise HTTPException(status_code=400, detail="Se requiere 'country_code' y 'dataset'.")
    try:
        return run_irmp(country_code, dataset)
    except KeyError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.post(
    "/snapshot",
    summary="Calcular, persistir y publicar el IRMP de un país",
    description=(
        "Calcula el IRMP contra el conjunto regional, guarda el snapshot con su "
        "desglose por dimensión y publica 'irmp.updated' para los demás ejes."
    ),
)
async def create_snapshot(
    payload: Dict[str, Any] = Body(
        ...,
        examples=[{
            "country_code": "DO",
            "period_end": "2025-12-31",
            "country_name": "República Dominicana",
            "region": "Caribe",
            "dataset": {
                "DO": {"gdp_cagr_3y": 4.5, "public_debt_gdp": 45.0},
                "CR": {"gdp_cagr_3y": 3.2, "public_debt_gdp": 63.0},
                "PA": {"gdp_cagr_3y": 5.1, "public_debt_gdp": 52.0},
            },
        }],
    ),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> Dict[str, Any]:
    country_code = payload.get("country_code")
    dataset = payload.get("dataset")
    period_end_raw = payload.get("period_end")
    if not country_code or not isinstance(dataset, dict) or not period_end_raw:
        raise HTTPException(
            status_code=400,
            detail="Se requiere 'country_code', 'dataset' y 'period_end'.",
        )
    try:
        period_end = date.fromisoformat(period_end_raw)
    except ValueError:
        raise HTTPException(status_code=400, detail="Formato de fecha inválido. Use YYYY-MM-DD")
    try:
        return compute_and_persist(
            db,
            country_code=country_code,
            dataset=dataset,
            period_end=period_end,
            country_name=payload.get("country_name"),
            region=payload.get("region"),
        )
    except KeyError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.get(
    "/{country_code}/latest",
    summary="Último IRMP persistido de un país",
)
async def latest_snapshot(
    country_code: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> Dict[str, Any]:
    snap = get_latest(db, country_code)
    if snap is None:
        return {"has_snapshot": False, "country_code": country_code}
    return {
        "has_snapshot": True,
        "country_code": country_code,
        "snapshot_id": snap.id,
        "period_end": str(snap.period_end),
        "irmp_score": float(snap.irmp_score),
        "risk_band": snap.risk_band.value if snap.risk_band else None,
        "peer_set_size": snap.peer_set_size,
        "model_version": snap.model_version,
        "dimensions": snap.breakdown,
    }


@router.get(
    "/{country_code}/history",
    summary="Historial de IRMP de un país",
)
async def snapshot_history(
    country_code: str,
    limit: int = Query(20, ge=1, le=100),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> Dict[str, Any]:
    snaps = get_history(db, country_code, limit)
    history = [
        {
            "period_end": str(s.period_end),
            "irmp_score": float(s.irmp_score),
            "risk_band": s.risk_band.value if s.risk_band else None,
        }
        for s in snaps
    ]
    return {"country_code": country_code, "history": history, "count": len(history)}
