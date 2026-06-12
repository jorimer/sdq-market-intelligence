"""Macro Monitor — API endpoints.

prefix: /api/v1/macro-monitor
"""
import logging
from typing import Any, Dict, Optional

import httpx
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from shared.auth.dependencies import get_current_user, require_role
from shared.auth.models import User, UserRole
from shared.data.bcrd_api import BCRD_BASE_URL, BCRD_VARIABLES, BcrdApiError, fetch_bcrd_variable
from shared.database.session import get_db
from shared.publications import catalog as pub_catalog
from shared.publications import service as pub_service
from shared.publications.models import Publication
from shared.settings.service import get_sector_api_base_url, get_sector_api_key
from modules.macro_monitor.service import (
    build_snapshot,
    delete_series,
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


@router.delete(
    "/series/{series_code}",
    summary="Eliminar todas las observaciones de una serie (admin)",
    description=(
        "Solo admin. Borra de MacroSeries todas las observaciones de un "
        "series_code. Mantenimiento para códigos huérfanos que el parser dejó "
        "de producir (la ingesta hace upsert y no poda). Idempotente."
    ),
)
async def delete_series_endpoint(
    series_code: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role(UserRole.admin)),
) -> Dict[str, Any]:
    deleted = delete_series(db, series_code)
    return {"series_code": series_code, "deleted": deleted}


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


def _describe_shape(payload: Any, sample: int = 3) -> Dict[str, Any]:
    """Summarize a JSON payload's structure without dumping all of it.

    Reports the top-level type/keys and, for the ``values`` list, its length and
    the keys + a few sample rows — enough to design the live parser from the real
    response without flooding the response with thousands of observations.
    """
    info: Dict[str, Any] = {"type": type(payload).__name__}
    if isinstance(payload, dict):
        info["keys"] = list(payload.keys())
        values = payload.get("values")
        if isinstance(values, list):
            vinfo: Dict[str, Any] = {"count": len(values)}
            if values:
                first = values[0]
                if isinstance(first, dict):
                    vinfo["item_keys"] = list(first.keys())
                vinfo["sample"] = values[:sample]
                vinfo["last"] = values[-1]
            info["values"] = vinfo
        if "name" in payload:
            info["name"] = payload["name"]
    elif isinstance(payload, list):
        info["count"] = len(payload)
        info["sample"] = payload[:sample]
    return info


@router.get(
    "/bcrd-test",
    summary="Diagnóstico: forma cruda de una variable del BCRD",
    description=(
        "Solo admin. Llama UN endpoint del BCRD con el token configurado y "
        "devuelve la forma de la respuesta (claves + muestra de 'values') para "
        "diseñar el parser live. No persiste nada."
    ),
)
async def bcrd_test(
    variable: str = Query("inflacion", description=f"Una de: {', '.join(BCRD_VARIABLES)}"),
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role(UserRole.admin)),
) -> Dict[str, Any]:
    token = get_sector_api_key(db, "bcrd")
    if not token:
        raise HTTPException(
            status_code=400,
            detail=(
                "Falta el token del BCRD o la fuente está deshabilitada. "
                "Configúralo y habilítalo en Configuración → BCRD."
            ),
        )
    base_url = get_sector_api_base_url(db, "bcrd") or None
    try:
        payload = (
            fetch_bcrd_variable(token, variable, base_url=base_url)
            if base_url
            else fetch_bcrd_variable(token, variable)
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except BcrdApiError as e:
        detail = (
            f"Token del BCRD rechazado: {e.message}" if e.is_auth else f"BCRD: {e.message}"
        )
        raise HTTPException(status_code=400 if e.is_auth else 502, detail=detail)
    except httpx.HTTPStatusError as e:
        body = e.response.text[:500] if e.response is not None else ""
        raise HTTPException(
            status_code=502,
            detail=f"BCRD respondió {e.response.status_code if e.response else '?'}: {body}",
        )
    except httpx.HTTPError as e:
        raise HTTPException(status_code=502, detail=f"Error de transporte hacia el BCRD: {e}")
    return {"variable": variable, "shape": _describe_shape(payload)}


@router.get(
    "/bcrd-egress-ip",
    summary="Diagnóstico: IPv4 de salida del backend (para la allowlist del BCRD)",
    description=(
        "Solo admin. Devuelve la IPv4 pública desde la que el backend hace sus "
        "llamadas salientes. Es la IP que debe autorizarse en la 'Lista de IP's' "
        "del BCRD. OJO: en Railway sin IPs estáticas esta IP puede cambiar."
    ),
)
async def bcrd_egress_ip(
    current_user: User = Depends(require_role(UserRole.admin)),
) -> Dict[str, Any]:
    try:  # pragma: no cover - network I/O
        resp = httpx.get("https://api4.ipify.org", params={"format": "json"}, timeout=15)
        resp.raise_for_status()
        ip = resp.json().get("ip", "")
    except httpx.HTTPError as e:  # pragma: no cover - network I/O
        raise HTTPException(status_code=502, detail=f"No se pudo determinar la IP de salida: {e}")
    return {
        "egress_ipv4": ip,
        "nota": (
            "Autoriza esta IPv4 en la 'Lista de IP's' del BCRD. En Railway sin IPs "
            "estáticas (plan Pro) puede cambiar; para algo permanente, habilita "
            "Static Outbound IPs y autoriza las 3 IPs asignadas."
        ),
    }


def _historico_extra(variable: str, year_from: int, year_to: int) -> Dict[str, Any]:
    """Build the date-range body for a BCRD Historico* endpoint."""
    if variable == "historico_ipc":
        return {
            "yearFrom": year_from, "monthFrom": 1, "yearTo": year_to, "monthTo": 12,
            "skipCount": 0, "maxResultCount": 100000,
        }
    # historico_tasas (exchange rates) — date range
    return {
        "fromDate": f"{year_from}-01-01", "toDate": f"{year_to}-12-31",
        "skipCount": 0, "maxResultCount": 100000,
    }


@router.get(
    "/bcrd-historico",
    summary="Diagnóstico: disponibilidad de histórico del BCRD (IPC / tasas)",
    description=(
        "Solo admin. Consulta un endpoint Historico* con un rango amplio y reporta "
        "cuántas observaciones devuelve y el primer/último registro, para decidir la "
        "profundidad del backfill. Variables: historico_ipc, historico_tasas."
    ),
)
async def bcrd_historico(
    variable: str = Query("historico_ipc", description="historico_ipc | historico_tasas"),
    year_from: int = Query(1980, description="Año inicial del rango a sondear"),
    year_to: int = Query(2026, description="Año final del rango a sondear"),
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role(UserRole.admin)),
) -> Dict[str, Any]:
    if variable not in ("historico_ipc", "historico_tasas"):
        raise HTTPException(status_code=400, detail="variable debe ser historico_ipc o historico_tasas")
    token = get_sector_api_key(db, "bcrd")
    if not token:
        raise HTTPException(status_code=400, detail="Falta el token del BCRD o la fuente está deshabilitada.")
    base_url = get_sector_api_base_url(db, "bcrd") or None
    extra = _historico_extra(variable, year_from, year_to)
    try:
        payload = fetch_bcrd_variable(token, variable, base_url=base_url or BCRD_BASE_URL, extra=extra)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except BcrdApiError as e:
        raise HTTPException(status_code=400 if e.is_auth else 502, detail=f"BCRD: {e.message}")
    except httpx.HTTPError as e:
        raise HTTPException(status_code=502, detail=f"Error de transporte hacia el BCRD: {e}")
    # Historico* responses may be a bare list, a {items:[...]} envelope, or {values:[...]}.
    items = payload
    if isinstance(payload, dict):
        items = payload.get("items") or payload.get("values") or payload.get("result") or []
    count = len(items) if isinstance(items, list) else 0
    first = items[0] if count else None
    last = items[-1] if count else None
    return {
        "variable": variable,
        "rango_consultado": f"{year_from}-{year_to}",
        "count": count,
        "first": first,
        "last": last,
        "item_keys": list(first.keys()) if isinstance(first, dict) else None,
    }


# ── Publicaciones BCRD (informes oficiales en PDF, digest IA) ──────
def _pub_summary(p: Publication) -> Dict[str, Any]:
    """Compact row for lists (no raw text; only the digest's resumen)."""
    digest = p.digest or {}
    return {
        "id": p.id,
        "report_key": p.report_key,
        "report_name": p.report_name,
        "period": p.period,
        "title": p.title,
        "source_url": p.source_url,
        "landing_url": p.landing_url,
        "sectors": p.sectors or [],
        "status": p.status,
        "published_at": p.published_at,
        "resumen": digest.get("resumen", ""),
        "has_digest": bool(digest.get("resumen") or digest.get("hallazgos")),
    }


@router.get(
    "/publications",
    summary="Listado de publicaciones BCRD ingeridas",
    description="Informes del BCRD con su digest IA. Filtra por 'report_key' (opcional).",
)
async def list_publications(
    report_key: Optional[str] = Query(None, description="Clave del informe (opcional)"),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> Dict[str, Any]:
    rows = pub_service.list_publications(db, report_key)
    return {"publications": [_pub_summary(r) for r in rows], "count": len(rows)}


@router.get(
    "/publications/catalog",
    summary="Catálogo + calendario de informes BCRD",
    description="Los informes recurrentes (cadencia, sectores, link al BCRD) y el último período ingerido de cada uno.",
)
async def publications_catalog(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> Dict[str, Any]:
    latest = {
        r.report_key: r.period
        for r in db.query(Publication).filter_by(status="ok").order_by(Publication.period.asc()).all()
    }
    reports = [
        {
            "key": spec.key,
            "name": spec.name,
            "cadence": spec.cadence,
            "sectors": list(spec.sectors),
            "landing_url": spec.landing_url,
            "latest_ingested_period": latest.get(spec.key),
        }
        for spec in pub_catalog.REPORTS.values()
    ]
    return {"reports": reports, "count": len(reports)}


@router.get(
    "/publications/{pub_id}",
    summary="Detalle de una publicación (con digest completo)",
)
async def publication_detail(
    pub_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> Dict[str, Any]:
    p = pub_service.get_publication(db, pub_id)
    if p is None:
        raise HTTPException(status_code=404, detail="Publicación no encontrada")
    out = _pub_summary(p)
    out["digest"] = p.digest or {}
    out["error"] = p.error
    return out


@router.post(
    "/publications/refresh",
    summary="Ingerir la última edición de los informes BCRD (admin)",
    description=(
        "Descarga, extrae y genera el digest IA de la última edición disponible. "
        "Idempotente: omite ediciones ya ingeridas salvo 'force'. Indica 'report_key' "
        "para procesar uno solo (más rápido)."
    ),
)
async def refresh_publications(
    report_key: Optional[str] = Query(None, description="Procesar solo este informe"),
    force: bool = Query(False, description="Re-ingerir aunque ya exista"),
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role(UserRole.admin)),
) -> Dict[str, Any]:
    if report_key and report_key not in pub_catalog.REPORTS:
        raise HTTPException(
            status_code=400,
            detail=f"Informe desconocido: {report_key}. Opciones: {', '.join(pub_catalog.report_keys())}",
        )
    keys = [report_key] if report_key else pub_catalog.report_keys()
    results = []
    for key in keys:
        row = pub_service.ingest_report(db, key, force=force)
        if row is None:
            results.append({"report_key": key, "status": "unavailable", "period": None})
        else:
            results.append({"report_key": key, "status": row.status, "period": row.period})
    ingested = sum(1 for r in results if r["status"] == "ok")
    return {"ingested_ok": ingested, "results": results}
