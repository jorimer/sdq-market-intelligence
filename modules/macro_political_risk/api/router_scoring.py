"""Macro-Political Risk — Scoring endpoints.

prefix: /api/v1/macro-political-risk

The core scoring is DB-agnostic and deterministic: the client supplies the
regional dataset and a target country, and the engine returns a full,
auditable IRMP breakdown.  Persistence will be layered on top later.
"""
import logging
from typing import Any, Dict

from fastapi import APIRouter, Body, Depends, HTTPException

from shared.auth.dependencies import get_current_user
from shared.auth.models import User
from modules.macro_political_risk.scoring.engine import run_irmp
from modules.macro_political_risk.scoring.weights import (
    DIMENSION_VARIABLES,
    DIMENSION_WEIGHTS,
    RISK_INCREASING_VARIABLES,
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
        example={
            "country_code": "DO",
            "dataset": {
                "DO": {"gdp_cagr_3y": 4.5, "public_debt_gdp": 45.0},
                "CR": {"gdp_cagr_3y": 3.2, "public_debt_gdp": 63.0},
                "PA": {"gdp_cagr_3y": 5.1, "public_debt_gdp": 52.0},
            },
        },
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
