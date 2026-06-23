"""ESG & Climate — API endpoints (IRC nacional).

prefix: /api/v1/esg-climate
Re-scoped 2026-06-18: the IRC is per-country over the Caribbean/LatAm panel.
Ingestion is server-side via the ``esg-sync`` console operation (ND-GAIN); these
endpoints are read-only + an admin purge.
"""
import logging
from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from shared.auth.dependencies import get_current_user, require_role
from shared.auth.models import User, UserRole
from shared.database.session import get_db
from modules.esg_climate.models.models import ESGScore, EnvIndicator
from modules.esg_climate.scoring.exposure import IRC_CONFIG
from modules.esg_climate.service import (
    IRC_PANEL,
    assemble_irc_dataset,
    get_latest,
    get_scores,
)

logger = logging.getLogger("sdq.api.esg_climate")

router = APIRouter()


async def _ai_insight(
    context: Dict[str, Any], template: str, audience: str = "inversionista",
) -> Dict[str, Any] | None:
    """Generate a Claude narrative via the cerebro route (axis=esg_climate); best-effort
    (returns None on any failure so the endpoint never breaks). Without an API key the
    engine returns a static fallback (``model_used == "static_fallback"``)."""
    try:
        from shared.narrative.claude_engine import narrative_engine
        res = await narrative_engine.generate(
            context, template=template, mode="detailed",
            axis="esg_climate", audience=audience,
        )
        return {"text": res.text, "model_used": res.model_used, "from_cache": res.from_cache}
    except Exception as e:  # noqa: BLE001 — AI is best-effort, never break the endpoint
        logger.warning("AI insight clima (%s) no disponible: %s", template, e)
        return None


@router.get("/weights", summary="Pesos del IRC climático (doctrina)")
async def weights(current_user: User = Depends(get_current_user)) -> Dict[str, Any]:
    return {
        "dimension_weights": IRC_CONFIG.dimension_weights,
        "dimension_variables": IRC_CONFIG.dimension_variables,
        "risk_increasing": sorted(IRC_CONFIG.risk_increasing),
        "direction": IRC_CONFIG.direction,
    }


@router.get("/backtest", summary="Backtest del IRC (validación vs mortalidad climática)")
async def backtest(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> Dict[str, Any]:
    import json

    from shared.settings.models import AppSetting
    row = db.query(AppSetting).filter(AppSetting.key == "esg_backtest_report").first()
    if not row or not row.value:
        return {"computed": False, "message": "Aún no hay backtest. Corre la operación «Backtest del IRC climático»."}
    return json.loads(row.value)


@router.get("/indicators", summary="IRC por país (panel Caribe/LatAm, más resiliente primero)")
async def indicators(
    period: Optional[str] = Query(None),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> Dict[str, Any]:
    rows = get_scores(db, period)
    items = [
        {"entity_key": r.entity_key, "country_name": IRC_PANEL.get(r.entity_key, r.entity_key),
         "period": r.period, "esg_score": r.esg_score, "band": r.band}
        for r in rows
    ]
    return {"indicators": items, "count": len(items),
            "period": items[0]["period"] if items else None}


@router.get(
    "/dataset",
    summary="Dataset ensamblado del IRC (real + rúbrica) con procedencia",
    description="El dataset por país que alimenta el IRC: real (ND-GAIN: físico/"
    "adaptativa/gobernanza) + rúbrica declarada (transición, hasta cablear energía/"
    "PEN). Incluye 'sources' (live|rubric) por variable para el badge real-vs-rúbrica.",
)
async def dataset(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> Dict[str, Any]:
    return assemble_irc_dataset(db)


@router.get("/score", summary="IRC de un país (con desglose por dimensión)")
async def latest(
    entity_key: str = Query("DOM"),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> Dict[str, Any]:
    s = get_latest(db, entity_key)
    if s is None:
        return {"has_score": False, "entity_key": entity_key}
    return {
        "has_score": True,
        "entity_key": entity_key,
        "country_name": IRC_PANEL.get(entity_key, entity_key),
        "period": s.period,
        "esg_score": s.esg_score,
        "band": s.band,
        "breakdown": s.breakdown,
        "model_version": s.model_version,
    }


@router.get(
    "/{entity_key}/insight",
    summary="Perspectiva de IA del IRC de un país — fase 2, lento (~10-15s)",
    description="Narrativa SCQA que explica la resiliencia climática del país: "
    "fortalezas/vulnerabilidades por dimensión, posición en el panel y procedencia real.",
)
async def insight(
    entity_key: str,
    audience: str = Query(
        "inversionista",
        description="Audiencia para orientar el insight (inversionista·gobierno·asegurador·"
                    "multilateral); una clave desconocida cae al default.",
    ),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> Dict[str, Any]:
    import statistics

    from modules.esg_climate.ai_context import climate_ai_context

    s = get_latest(db, entity_key)
    if s is None:
        return {"has_score": False, "entity_key": entity_key, "ai_insight": None}

    peers = [r for r in get_scores(db, s.period) if r.esg_score is not None]
    peers.sort(key=lambda r: r.esg_score, reverse=True)   # most resilient first
    rank = next((i + 1 for i, r in enumerate(peers) if r.entity_key == entity_key), None)
    vals = [float(r.esg_score) for r in peers]
    dist = ({"mean": round(statistics.mean(vals), 2), "min": round(min(vals), 2),
             "max": round(max(vals), 2), "spread": round(max(vals) - min(vals), 2)}
            if vals else None)
    score = {"esg_score": s.esg_score, "band": s.band, "period": s.period, "breakdown": s.breakdown}
    ctx = climate_ai_context(entity_key, score, country_name=IRC_PANEL.get(entity_key),
                             rank=rank, n_countries=len(peers), distribution=dist)
    return {"has_score": True, "entity_key": entity_key,
            "ai_insight": await _ai_insight(ctx, "climate_outlook", audience)}


@router.delete(
    "/data",
    summary="Purgar los scores IRC persistidos (admin)",
    description="Borra todos los scores e indicadores ESG/clima persistidos.",
)
async def purge_data(
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role(UserRole.admin)),
) -> Dict[str, Any]:
    scores = db.query(ESGScore).delete()
    indicators_ = db.query(EnvIndicator).delete()
    db.commit()
    logger.info("Purgado dato ESG: %d scores, %d indicadores", scores, indicators_)
    return {"scores_deleted": scores, "indicators_deleted": indicators_}
