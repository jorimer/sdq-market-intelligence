"""Pension Intel (SIPEN) — API endpoints.

prefix: /api/v1/pension-intel

F0 exposes the read-only data spine (system series, AFP catalog, per-AFP series,
latest snapshot, sync status) plus an admin-only sync trigger. Scoring and AI
insight endpoints land in F1/F2.
"""
import logging
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from shared.auth.dependencies import get_current_user, require_role
from shared.auth.models import User, UserRole
from shared.database.session import get_db
from modules.pension_intel.models.models import (
    PensionEntity,
    PensionSeries,
    PensionSnapshot,
)

logger = logging.getLogger("sdq.api.pension_intel")

router = APIRouter()

# Audiences served by the pension pulse narrative (see cerebro AUDIENCE_FRAMES).
_AUDIENCES = {"inversionista", "regulador", "afiliado", "gobierno"}


async def _ai_insight(
    context: Dict[str, Any], audience: str = "inversionista", deep: bool = False,
) -> Dict[str, Any] | None:
    """Claude narrative via the cerebro route (axis=pension_intel); best-effort
    (returns None on any failure so the endpoint never breaks). Without an API key
    the engine serves a static fallback."""
    try:
        from shared.narrative.claude_engine import narrative_engine
        res = await narrative_engine.generate(
            context, template="pension_pulse", mode="deep" if deep else "detailed",
            axis="pension_intel", audience=audience,
        )
        return {"text": res.text, "model_used": res.model_used, "from_cache": res.from_cache}
    except Exception as e:  # noqa: BLE001 — AI is best-effort, never break the endpoint
        logger.warning("AI insight pensiones no disponible: %s", e)
        return None


def _serialize(s: PensionSeries) -> Dict[str, Any]:
    return {
        "code": s.series_code,
        "period": s.period,
        "value": s.value,
        "unit": s.unit,
        "frequency": s.frequency,
        "entity_slug": s.entity_slug,
        "source": s.source,
    }


@router.get("/series")
async def list_series(
    entity_slug: Optional[str] = Query(None, description="AFP slug; omitir = series del sistema"),
    system_only: bool = Query(False, description="Solo series nacionales (entity_slug NULL)"),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Pension series. By default returns all; filter by AFP or system-only."""
    q = db.query(PensionSeries)
    if system_only:
        q = q.filter(PensionSeries.entity_slug.is_(None))
    elif entity_slug:
        q = q.filter(PensionSeries.entity_slug == entity_slug)
    rows = q.order_by(PensionSeries.series_code, PensionSeries.period).all()
    return {"series": [_serialize(s) for s in rows], "count": len(rows)}


@router.get("/entities")
async def list_entities(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """The AFP catalog."""
    rows = db.query(PensionEntity).order_by(PensionEntity.name).all()
    return {
        "entities": [
            {"slug": e.slug, "name": e.name, "afp_code": e.afp_code, "is_active": e.is_active}
            for e in rows
        ],
        "count": len(rows),
    }


@router.get("/snapshot")
async def latest_snapshot(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """The most recent system snapshot (headline national figures)."""
    snap = (
        db.query(PensionSnapshot)
        .order_by(PensionSnapshot.period.desc())
        .first()
    )
    if snap is None:
        return {"snapshot": None}
    return {
        "snapshot": {
            "period": snap.period,
            "headline": snap.headline,
            "series_count": snap.series_count,
            "entity_count": snap.entity_count,
            "model_version": snap.model_version,
        }
    }


@router.get("/pulse")
async def system_pulse(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """The national pension pulse: system headline + per-AFP rentabilidad dispersion."""
    from modules.pension_intel.service import build_system_pulse
    return build_system_pulse(db)


@router.get("/insight")
async def insight(
    audience: str = Query("inversionista"),
    deep: bool = Query(False),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """AI narrative (Cerebro) over the pension pulse. Best-effort."""
    from modules.pension_intel.ai_context import pension_ai_context
    from modules.pension_intel.service import build_system_pulse
    aud = audience if audience in _AUDIENCES else "inversionista"
    context = pension_ai_context(build_system_pulse(db))
    result = await _ai_insight(context, audience=aud, deep=deep)
    # Same contract as the other axes: the narrative travels under `ai_insight`
    # (the frontend AiInsightCard reads `data.ai_insight`).
    return {"audience": aud, "ai_insight": result}


@router.get("/sync-status")
async def sync_status(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Live status of the SIPEN sync (for the Datos page)."""
    from shared.operations.service import get_status
    return get_status(db, "sipen-sync")


@router.post("/sync")
async def trigger_sync(
    current_user: User = Depends(require_role(UserRole.admin)),
):
    """Trigger the SIPEN sync (admin only)."""
    from shared.operations.service import trigger
    return trigger("sipen-sync", origin="api", user_id=current_user.id)
