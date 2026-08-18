"""API del Data Registry — ``/api/v1/registry`` (solo lectura, cualquier autenticado).

Superficie de consulta del catálogo de datos normalizado (Fase 1 del motor de
research). La consume el piloto manual de la Fase 2 (analista + Claude) para saber,
por eje, qué se mide con qué procedencia antes de responder una pregunta libre —y,
más adelante, el orquestador de la Fase 4. Estrictamente read-only: no calcula
productos ni escribe nada.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from shared.auth.dependencies import get_current_user
from shared.auth.models import User
from shared.database.session import get_db
from shared.registry.service import build_data_registry
from shared.registry.signals import AxisRegistry, DataRegistry, VariableSignal

router = APIRouter()


def _signal_dict(s: VariableSignal) -> Dict[str, Any]:
    return {
        "key": s.key, "label": s.label, "state": s.state, "dimension": s.dimension,
        "weight": s.weight, "source": s.source, "cadence": s.cadence,
        "value": s.value, "period": s.period, "real_fraction": s.real_fraction, "note": s.note,
        # El ALCANCE viaja con el valor. Sin él, un consumidor lee `value` y no puede saber
        # si le sirven la cifra del país o la de un sujeto del panel: es exactamente el
        # defecto que publicó la pobreza extrema de cibao_norte como nacional, y hasta acá
        # la API externa seguía sin exponer la distinción.
        "scope": s.scope,
        # La serie completa cuando el eje la sirve. Vacía NO significa que no exista: el eje
        # publica un punto y nada más (ver `VariableSignal.history`).
        "history": [{"period": p, "value": v} for p, v in s.history],
    }


def _axis_dict(a: AxisRegistry) -> Dict[str, Any]:
    return {
        "sector_key": a.sector_key, "display_name": a.display_name, "source": a.source,
        "implemented": a.implemented, "degraded": a.degraded, "period": a.period,
        "coverage_real": a.coverage_real, "coverage_kind": a.coverage_kind,
        "state_counts": a.state_counts,
        "note": a.note, "signals": [_signal_dict(s) for s in a.signals],
    }


def _registry_dict(reg: DataRegistry) -> Dict[str, Any]:
    return {
        "generated_at": reg.generated_at,
        "summary": reg.summary,
        "axes": [_axis_dict(a) for a in reg.axes],
    }


@router.get("")
def get_registry(
    db: Session = Depends(get_db),
    _user: User = Depends(get_current_user),
) -> Dict[str, Any]:
    """Registro completo: la señal por-variable normalizada de todos los ejes."""
    return _registry_dict(build_data_registry(db))


@router.get("/search")
def search_signals(
    q: str = Query(..., min_length=2, description="Texto a buscar en clave/etiqueta/fuente/eje"),
    state: Optional[str] = Query(None, description="Filtrar por estado: real | rubric | gap"),
    db: Session = Depends(get_db),
    _user: User = Depends(get_current_user),
) -> Dict[str, Any]:
    """Busca variables por texto (clave, etiqueta, fuente, eje) y opcionalmente estado.

    Es la superficie que el analista/orquestador usa para mapear una sub-pregunta a
    los indicadores del catálogo que la responden con dato real."""
    needle = q.strip().lower()
    reg = build_data_registry(db)
    hits: List[Dict[str, Any]] = []
    for a in reg.axes:
        for s in a.signals:
            if state and s.state != state:
                continue
            hay = " ".join((s.key, s.label, s.source, s.dimension,
                            a.sector_key, a.display_name)).lower()
            if needle in hay:
                hit = _signal_dict(s)
                hit["sector_key"] = a.sector_key
                hit["display_name"] = a.display_name
                hits.append(hit)
    return {"query": q, "state": state, "count": len(hits), "results": hits}


@router.get("/{sector_key}")
def get_axis(
    sector_key: str,
    db: Session = Depends(get_db),
    _user: User = Depends(get_current_user),
) -> Dict[str, Any]:
    """Registro de un solo eje por ``sector_key``."""
    reg = build_data_registry(db)
    for a in reg.axes:
        if a.sector_key == sector_key:
            return _axis_dict(a)
    raise HTTPException(status_code=404, detail=f"Eje '{sector_key}' no está en el catálogo.")
