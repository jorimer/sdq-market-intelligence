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


async def _ai_insight(
    context: Dict[str, Any], template: str, audience: str = "formulador_politica",
    deep: bool = False,
) -> Dict[str, Any] | None:
    """Generate a Claude narrative via the cerebro route (axis=social_dev); best-effort
    (returns None on any failure so the endpoint never breaks). Without an API key the
    engine returns a static fallback (``model_used == "static_fallback"``).
    ``deep`` → the opt-in extended "full analysis" version."""
    try:
        from shared.narrative.claude_engine import narrative_engine
        res = await narrative_engine.generate(
            context, template=template, mode="deep" if deep else "detailed",
            axis="social_dev", audience=audience,
        )
        return {"text": res.text, "model_used": res.model_used, "from_cache": res.from_cache}
    except Exception as e:  # noqa: BLE001 — AI is best-effort, never break the endpoint
        logger.warning("AI insight social (%s) no disponible: %s", template, e)
        return None

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
    "/validation/convergent",
    summary="Validez convergente del IDM (ranking regional vs IDH regional del PNUD)",
)
async def convergent_validity(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> Dict[str, Any]:
    from modules.social_dev.operations import IDM_VALIDITY_KEY
    from shared.settings.models import AppSetting
    from shared.validation.frescura import con_frescura
    import json

    row = db.query(AppSetting).filter(AppSetting.key == IDM_VALIDITY_KEY).first()
    if not row:
        return {"has_report": False}
    return {"has_report": True, **con_frescura(json.loads(row.value), "social_dev", db)}


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
    period: Optional[str] = Query(None, description="Período; por defecto, el último."),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> Dict[str, Any]:
    return assemble_idm_dataset(db, period=period)


@router.get("/publications", summary="Estudios de la ONE (digest IA)")
async def publications(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> Dict[str, Any]:
    from shared.publications import catalog as pub_catalog
    from shared.publications import service as pub_service

    one_keys = set(pub_catalog.report_keys("ONE"))
    rows = [r for r in pub_service.list_publications(db) if r.report_key in one_keys]
    items = [
        {"id": r.id, "report_key": r.report_key, "report_name": r.report_name,
         "period": r.period, "landing_url": r.landing_url, "status": r.status,
         "sectors": r.sectors or [], "resumen": (r.digest or {}).get("resumen", ""),
         "hallazgos": (r.digest or {}).get("hallazgos", [])}
        for r in rows
    ]
    return {"publications": items, "count": len(items)}


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


@router.get(
    "/{entity_key}/insight",
    summary="Perspectiva de IA del desarrollo (IDM) por región — fase 2, lento (~10-15s)",
    description="Narrativa SCQA que explica el IDM de una región: fortalezas/rezagos por "
    "dimensión, posición en la distribución (desigualdad) y procedencia real-vs-rúbrica.",
)
async def insight(
    entity_key: str,
    audience: str = Query(
        "formulador_politica",
        description="Audiencia para orientar el insight (formulador_politica·gobierno_regional·"
                    "multilateral·inversionista_impacto); una clave desconocida cae al default.",
    ),
    deep: bool = Query(False, description="Versión extendida (análisis completo, ~700-1000 palabras)."),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> Dict[str, Any]:
    from shared.data.one_client import region_catalog
    from modules.social_dev.ai_context import social_ai_context

    s = get_latest(db, entity_key)
    if s is None:
        return {"has_score": False, "entity_key": entity_key, "ai_insight": None}

    # Rank + distribution among the regions of the same (latest) period — inequality read.
    from shared.indices.panel import annotate_panel_position
    peers = [r for r in get_scores(db, s.period) if r.development_score is not None]
    peers.sort(key=lambda r: r.development_score, reverse=True)
    rank = next((i + 1 for i, r in enumerate(peers) if r.entity_key == entity_key), None)
    dist = distribution_stats([r.development_score for r in peers])
    # E2E-SYS1: posición estructurada en el panel (antes solo iba a la prosa IA).
    panel_position = annotate_panel_position(
        s.development_score, [r.development_score for r in peers])
    name = dict(region_catalog()).get(entity_key)
    sources = assemble_idm_dataset(db, period=s.period)["sources"].get(entity_key)
    score = {"development_score": s.development_score, "band": s.band,
             "period": s.period, "breakdown": s.breakdown}
    ctx = social_ai_context(entity_key, score, region_name=name, sources=sources,
                            rank=rank, n_regions=len(peers), distribution=dist)
    return {"has_score": True, "entity_key": entity_key,
            "panel_position": panel_position,
            "ai_insight": await _ai_insight(ctx, "social_outlook", audience, deep)}
