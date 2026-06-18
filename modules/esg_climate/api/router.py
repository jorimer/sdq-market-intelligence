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


@router.get("/weights", summary="Pesos del IRC climático (doctrina)")
async def weights(current_user: User = Depends(get_current_user)) -> Dict[str, Any]:
    return {
        "dimension_weights": IRC_CONFIG.dimension_weights,
        "dimension_variables": IRC_CONFIG.dimension_variables,
        "risk_increasing": sorted(IRC_CONFIG.risk_increasing),
        "direction": IRC_CONFIG.direction,
    }


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
