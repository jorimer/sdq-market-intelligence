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
    assemble_iai_dataset,
    compute_and_persist,
    get_latest,
    get_sectors,
    seed_sectors,
)

logger = logging.getLogger("sdq.api.sector_intel")

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
        logger.warning("AI insight sector (%s) no disponible: %s", template, e)
        return None

_EXAMPLE_DATASET = {
    "turismo": {"macro_exposure": 56, "ease_of_business": 65, "operating_cost": 40,
                "labor_availability": 75, "skills_index": 60, "regulatory_quality": 62,
                "regulatory_volatility": 30, "sector_growth": 9.5, "sector_size": 8.9},
    "comercio": {"macro_exposure": 50, "ease_of_business": 50, "operating_cost": 50,
                 "labor_availability": 50, "skills_index": 50, "regulatory_quality": 50,
                 "regulatory_volatility": 50, "sector_growth": 5.6, "sector_size": 12.9},
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
    payload: Dict[str, Any] = Body(..., examples=[{"sector_code": "turismo", "dataset": _EXAMPLE_DATASET}]),
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
        examples=[{
            "period": "2025",
            "dataset": _EXAMPLE_DATASET,
            "sgps_inputs": {
                "turismo": {"historical": 75, "structural": 80},
                "comercio": {"historical": 60, "structural": 70},
            },
        }],
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


@router.get(
    "/dataset",
    summary="Dataset ensamblado del IAI (real + rúbrica) con procedencia",
    description=(
        "El dataset por sector que alimenta el IAI: dato real (tamaño/crecimiento del "
        "BCRD, exposición macro del contrato) + rúbrica declarada (negocios/talento/"
        "regulatoria). Incluye 'sources' (live|rubric) por variable para el badge "
        "real-vs-rúbrica. Single-source: el snapshot y la UI puntúan lo mismo."
    ),
)
async def dataset(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> Dict[str, Any]:
    return assemble_iai_dataset(db)


@router.get(
    "/validation",
    summary="Backtest sectorial (Gate E · empleo formal)",
    description="Devuelve el último Gate E persistido: IC de rango (Spearman) entre el "
    "IAI en T y el crecimiento del empleo formal por rama en T+1, con su IC, IC parcial "
    "(controlando crecimiento) y spread por quintil. Direccional.",
)
async def validation(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> Dict[str, Any]:
    import json

    from modules.sector_intel.operations import GATE_E_KEY
    from shared.settings.models import AppSetting

    row = db.query(AppSetting).filter(AppSetting.key == GATE_E_KEY).first()
    if not row:
        return {"has_report": False}
    return {"has_report": True, **json.loads(row.value)}


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


@router.get(
    "/{sector_code}/insight",
    summary="Perspectiva de IA del sector (IAI/SGPS) — fase 2, lento (~10-15s)",
    description="Narrativa SCQA que explica el atractivo del sector (IAI), sus motores "
    "por dimensión y la aceleración (SGPS), siendo honesta sobre qué es real vs rúbrica.",
)
async def insight(
    sector_code: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> Dict[str, Any]:
    from modules.sector_intel.ai_context import sector_ai_context

    s = get_latest(db, sector_code)
    if s is None:
        return {"has_score": False, "sector_code": sector_code, "ai_insight": None}
    name = next((sec.name for sec in get_sectors(db) if sec.code == sector_code), None)
    latest = {
        "sector_code": sector_code, "period": s.period, "iai_score": s.iai_score,
        "iai_band": s.iai_band, "sgps_score": s.sgps_score, "iai_breakdown": s.iai_breakdown,
    }
    ctx = sector_ai_context(latest, sector_name=name, sgps_detail=s.sgps_breakdown)
    return {"has_score": True, "sector_code": sector_code,
            "ai_insight": await _ai_insight(ctx, "sector_outlook")}
