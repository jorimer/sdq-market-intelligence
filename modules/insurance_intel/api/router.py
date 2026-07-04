"""Insurance Intel (SIS · SISALRIL) — API endpoints.

prefix: /api/v1/insurance-intel

F1a exposes the read-only market spine (market series, latest snapshot, national
Pulse) + an AI insight over the pulse + an admin-only sync trigger. The per-insurer
ISF ranking/detail endpoints are wired but return empty until the F1b audited-
financials backfill populates ``insurance_ratings`` — honest, never fabricated.
"""
import logging
from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from shared.auth.dependencies import get_current_user, require_role
from shared.auth.models import User, UserRole
from shared.database.session import get_db
from modules.insurance_intel.models.models import (
    InsuranceRating,
    InsuranceSeries,
    InsuranceSnapshot,
)
from modules.insurance_intel.scoring.isf import compute_isf
from modules.insurance_intel.service import build_market_pulse

logger = logging.getLogger("sdq.api.insurance_intel")

router = APIRouter()

_AUDIENCES = {"inversionista", "regulador", "asegurado", "gobierno"}


async def _ai_insight(context: Dict[str, Any], audience: str = "inversionista",
                      deep: bool = False, template: str = "insurance_pulse") -> Optional[Dict[str, Any]]:
    """Claude narrative via the cerebro route (axis=insurance_intel); best-effort."""
    try:
        from shared.narrative.claude_engine import narrative_engine
        res = await narrative_engine.generate(
            context, template=template, mode="deep" if deep else "detailed",
            axis="insurance_intel", audience=audience,
        )
        return {"text": res.text, "model_used": res.model_used, "from_cache": res.from_cache}
    except Exception as e:  # noqa: BLE001 — AI is best-effort, never break the endpoint
        logger.warning("AI insight seguros (%s) no disponible: %s", template, e)
        return None


def _serialize(s: InsuranceSeries) -> Dict[str, Any]:
    return {
        "code": s.series_code, "period": s.period, "value": s.value, "unit": s.unit,
        "frequency": s.frequency, "entity_slug": s.entity_slug, "dimension": s.dimension,
        "source": s.source,
    }


@router.get("/series")
async def list_series(
    dimension: Optional[str] = Query(None, description="ramo (línea) slug; omitir = totales"),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    q = db.query(InsuranceSeries).filter(InsuranceSeries.entity_slug.is_(None))
    if dimension:
        q = q.filter(InsuranceSeries.dimension == dimension)
    rows = q.order_by(InsuranceSeries.period.desc()).limit(1000).all()
    return {"series": [_serialize(s) for s in rows], "count": len(rows)}


@router.get("/snapshot")
async def latest_snapshot(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    snap = db.query(InsuranceSnapshot).order_by(InsuranceSnapshot.period.desc()).first()
    if not snap:
        return {"snapshot": None}
    return {"snapshot": {
        "period": snap.period, "headline": snap.headline,
        "series_count": snap.series_count, "entity_count": snap.entity_count,
        "model_version": snap.model_version,
    }}


@router.get("/pulse")
async def market_pulse(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return build_market_pulse(db)


@router.get("/health-pulse")
async def health_pulse(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """SFS national health-coverage pulse (SISALRIL/CNSS). None until the SFS sync runs."""
    from modules.insurance_intel.service import build_health_pulse
    hp = build_health_pulse(db)
    return {"health_coverage": hp, "has_data": hp is not None}


@router.get("/insight")
async def pulse_insight(
    audience: str = Query("inversionista"),
    deep: bool = Query(False),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    from modules.insurance_intel.ai_context import market_pulse_context
    pulse = build_market_pulse(db)
    if not pulse.get("has_data"):
        return {"audience": audience, "ai_insight": None, "has_data": False}
    aud = audience if audience in _AUDIENCES else "inversionista"
    ai = await _ai_insight(market_pulse_context(pulse), audience=aud, deep=deep)
    return {"audience": aud, "ai_insight": ai, "has_data": True}


@router.get("/rankings")
async def rankings(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Insurers ranked by ISF. Empty until F1b (audited financials) — honest."""
    results = compute_isf(db)
    ranked = [
        {"rank": i + 1, "slug": r["slug"], "overall_score": r["overall_score"],
         "band": r["band"], "coverage": r["coverage"], "period": r["period"]}
        for i, r in enumerate(results) if r["overall_score"] is not None
    ]
    return {"rankings": ranked, "count": len(ranked),
            "scale": "ISF 0-100 (Sólida/Adecuada/En vigilancia/Frágil)",
            "note": None if ranked else "ISF pendiente: estados financieros auditados no ingeridos (F1b)."}


@router.get("/{slug}/detail")
async def entity_detail(
    slug: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    r = db.query(InsuranceRating).filter(InsuranceRating.entity_slug == slug).first()
    if not r:
        return {"found": False, "slug": slug,
                "note": "Sin ISF para esta aseguradora (estados financieros no ingeridos)."}
    return {"found": True, "slug": slug, "overall_score": r.overall_score,
            "band": r.band, "coverage": r.coverage, "dimensions": r.dimensions}


@router.get("/entity-insight/{slug}")
async def entity_insight(
    slug: str,
    audience: str = Query("inversionista"),
    deep: bool = Query(False),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    from modules.insurance_intel.ai_context import insurance_entity_context
    results = compute_isf(db)
    rating = next((r for r in results if r["slug"] == slug), None)
    if not rating or rating.get("overall_score") is None:
        return {"slug": slug, "ai_insight": None, "has_data": False}
    aud = audience if audience in _AUDIENCES else "inversionista"
    ai = await _ai_insight(insurance_entity_context(rating, results), audience=aud,
                           deep=deep, template="insurance_entity")
    return {"slug": slug, "audience": aud, "ai_insight": ai, "has_data": True}


@router.post("/sync")
async def trigger_sync(
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role(UserRole.admin)),
):
    from modules.insurance_intel.sis_sync import sis_insurance_sync
    return sis_insurance_sync(db, mode="live")


@router.post("/financials/sync")
async def trigger_financials_sync(
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role(UserRole.admin)),
):
    from modules.insurance_intel.financials_sync import sis_financials_sync
    return sis_financials_sync(db)


@router.post("/health/sync")
async def trigger_health_sync(
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role(UserRole.admin)),
):
    from modules.insurance_intel.sisalril_sync import sisalril_sfs_sync
    return sisalril_sfs_sync(db, mode="live")
