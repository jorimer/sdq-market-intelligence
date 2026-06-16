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
    assemble_irmp_dataset,
    compute_and_persist,
    get_country_variables,
    get_history,
    get_latest,
)
from modules.macro_political_risk.ai_context import irmp_ai_context

logger = logging.getLogger("sdq.api.macro_political_risk")

router = APIRouter()


async def _ai_insight(context: Dict[str, Any], template: str) -> Dict[str, Any] | None:
    """Generate a Claude narrative from *context*; best-effort (returns None on any
    failure so the endpoint never breaks). These endpoints are ``async def``, so we
    await the engine directly. Without an API key it returns a static fallback
    (``model_used == "static_fallback"``), passed through.
    """
    try:
        from shared.narrative.claude_engine import narrative_engine
        res = await narrative_engine.generate(context, template=template, mode="detailed")
        return {"text": res.text, "model_used": res.model_used, "from_cache": res.from_cache}
    except Exception as e:  # noqa: BLE001 — AI is best-effort, never break the endpoint
        logger.warning("AI insight IRMP (%s) no disponible: %s", template, e)
        return None


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
    with_ai: bool = Query(False, description="Incluir evaluación de riesgo de IA (Claude) — fase 2, lento (~10-15s)"),
    current_user: User = Depends(get_current_user),
) -> Dict[str, Any]:
    country_code = payload.get("country_code")
    dataset = payload.get("dataset")
    if not country_code or not isinstance(dataset, dict):
        raise HTTPException(status_code=400, detail="Se requiere 'country_code' y 'dataset'.")
    try:
        result = run_irmp(country_code, dataset)
    except KeyError as e:
        raise HTTPException(status_code=404, detail=str(e))
    result["ai_insight"] = None
    if with_ai:
        ctx = irmp_ai_context(result, payload.get("country_name"))
        result["ai_insight"] = await _ai_insight(ctx, "risk_assessment")
    return result


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
    "/wgi",
    summary="Valores WGI en vivo persistidos (Banco Mundial)",
    description=(
        "Devuelve los indicadores de gobernanza WGI persistidos por el sync, "
        "agrupados por país: {iso: {variable: valor}}. Sin 'period' usa el más "
        "reciente disponible. Permite al frontend superponer dato real sobre el "
        "conjunto regional sin fabricar valores faltantes."
    ),
)
async def wgi_live(
    period: str | None = Query(None, description="Período WGI (ej. '2024'); por defecto el más reciente."),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> Dict[str, Any]:
    return get_country_variables(db, period=period, source="WGI")


@router.get(
    "/variables",
    summary="Todas las variables IRMP persistidas (WGI + WDI + IMF + declaradas)",
    description=(
        "Devuelve TODO el dato real/declarado persistido para el IRMP, agrupado "
        "por país: {iso: {variable: valor}}, sin filtrar por fuente. El frontend "
        "lo superpone sobre el conjunto ilustrativo para correr el índice sobre "
        "dato real sin fabricar las variables aún no sourced."
    ),
)
async def all_variables(
    period: str | None = Query(None, description="Período (ej. '2024'); por defecto el más reciente."),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> Dict[str, Any]:
    return get_country_variables(db, period=period, source=None)


@router.get(
    "/dataset",
    summary="Dataset IRMP ensamblado (dato real + rúbrica declarada)",
    description=(
        "Devuelve el dataset completo por país que alimenta el índice: la rúbrica "
        "declarada (doctrina) superpuesta con el dato real persistido (real gana), "
        "más un mapa de procedencia por variable (live/rubric). Fuente única para "
        "el snapshot y el frontend."
    ),
)
async def irmp_dataset(
    period: str | None = Query(None, description="Período (ej. '2024'); por defecto el más reciente."),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> Dict[str, Any]:
    return assemble_irmp_dataset(db, period=period)


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
