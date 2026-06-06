"""Macro Monitor — API endpoints.

prefix: /api/v1/macro-monitor
"""
import logging
from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from shared.auth.dependencies import get_current_user
from shared.auth.models import User
from shared.database.session import get_db
from modules.macro_monitor.service import (
    build_snapshot,
    get_indicators,
    get_series,
    get_snapshot,
    ingest_series,
)

logger = logging.getLogger("sdq.api.macro_monitor")

router = APIRouter()


@router.post(
    "/refresh",
    summary="Ingerir series y recomputar el snapshot macro",
    description="Pull de fuentes (BCRD), cálculo de momentum + señales, persiste y publica 'macro.updated'.",
)
async def refresh(
    period: Optional[str] = Query(None, description="Etiqueta del período (por defecto, el último observado)"),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> Dict[str, Any]:
    ingest_series(db)
    try:
        return build_snapshot(db, period=period)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get(
    "/indicators",
    summary="Indicadores macro con su momentum",
    description="Último momentum (cambio, aceleración, tendencia, banda de incertidumbre) por serie.",
)
async def indicators(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> Dict[str, Any]:
    items = get_indicators(db)
    return {"indicators": items, "count": len(items)}


@router.get(
    "/series/{series_code}",
    summary="Histórico de una serie + momentum",
    description="Observaciones (período-ordenadas) de una serie y su lectura de momentum (para la proyección).",
)
async def series_detail(
    series_code: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> Dict[str, Any]:
    return get_series(db, series_code)


@router.get(
    "/snapshot",
    summary="Snapshot macro persistido",
    description="Momentum + señales del período indicado (o el último).",
)
async def snapshot(
    period: Optional[str] = Query(None, description="Período (YYYY, YYYY-Qn, YYYY-MM). Si se omite, el último."),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> Dict[str, Any]:
    snap = get_snapshot(db, period)
    if snap is None:
        return {"has_snapshot": False, "period": period}
    return {
        "has_snapshot": True,
        "period": snap.period,
        "momentum": snap.momentum,
        "signals": snap.signals,
        "series_count": snap.series_count,
        "signal_count": snap.signal_count,
        "model_version": snap.model_version,
    }


@router.get(
    "/signals",
    summary="Señales de alerta temprana",
    description="Señales del snapshot (Reinhart-Rogoff deuda, Calvo freno súbito).",
)
async def signals(
    period: Optional[str] = Query(None, description="Período. Si se omite, el último."),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> Dict[str, Any]:
    snap = get_snapshot(db, period)
    if snap is None:
        return {"period": period, "signals": [], "count": 0}
    sigs = snap.signals or []
    return {"period": snap.period, "signals": sigs, "count": len(sigs)}
