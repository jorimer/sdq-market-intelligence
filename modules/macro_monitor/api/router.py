"""Macro Monitor — API endpoints.

prefix: /api/v1/macro-monitor

Las operaciones se declaran ``def`` (síncronas), NO ``async def``. Todo el trabajo
aguas abajo es bloqueante: SQLAlchemy síncrono, descargas del CDN del BCRD, parseo
de Excel y llamadas a Claude (~10-60s en layouts difíciles). FastAPI corre las
funciones ``def`` en su threadpool, fuera del event loop; un ``async def`` las
correría DENTRO del loop y una sola ingesta lenta congelaría al único worker de
uvicorn → 502 en cascada. No las conviertas a ``async def`` sin volver async todo
el I/O subyacente. (Las cargas largas —batch/canónico— van a Celery/hilo aparte.)
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
from modules.macro_monitor.comunicados import service as com_service
from shared.settings.service import get_sector_api_base_url, get_sector_api_key
from modules.macro_monitor.service import (
    backfill_historico,
    build_snapshot,
    cross_validate_excel,
    delete_series,
    excel_catalog_summary,
    get_canonical_registry,
    get_excel_coverage,
    get_fiscal_pulse,
    get_indicators,
    get_series,
    get_snapshot,
    ingest_excel_file,
    ingest_series,
    start_canonical_ingest_background,
    start_excel_batch_background,
)

logger = logging.getLogger("sdq.api.macro_monitor")

router = APIRouter()


def _ai_insight(
    context: Dict[str, Any], template: str, audience: str = "comite",
    deep: bool = False,
) -> Optional[Dict[str, Any]]:
    """Generate a Claude narrative via the cerebro route (axis=macro_monitor); best-effort
    (returns None on any failure so the endpoint never breaks). ``deep`` → the opt-in
    extended "full analysis" version.

    These endpoints are sync ``def`` (threadpool), so we drive the async engine with
    ``asyncio.run`` in this worker thread — the blocking Anthropic call runs off the main
    event loop. Without an API key the engine returns a static fallback
    (``model_used == "static_fallback"``), which we pass through.
    """
    import asyncio
    try:
        from shared.narrative.claude_engine import narrative_engine
        res = asyncio.run(narrative_engine.generate(
            context, template=template, mode="deep" if deep else "detailed",
            axis="macro_monitor", audience=audience,
        ))
        return {"text": res.text, "model_used": res.model_used, "from_cache": res.from_cache}
    except Exception as e:  # noqa: BLE001 — AI is best-effort, never break the endpoint
        logger.warning("AI insight macro (%s) no disponible: %s", template, e)
        return None


@router.post(
    "/refresh",
    summary="Ingerir series y recomputar el snapshot macro",
    description="Pull de fuentes (BCRD), cálculo de momentum + señales, persiste y publica 'macro.updated'.",
)
def refresh(
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
def indicators(
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
def series_detail(
    series_code: str,
    with_ai: bool = Query(False, description="Incluir insight de IA (Claude) — fase 2, lento (~10-15s)"),
    audience: str = Query(
        "comite",
        description="Audiencia para orientar el insight (comite·inversionista·gobierno·empresa); "
                    "una clave desconocida cae al default.",
    ),
    deep: bool = Query(False, description="Versión extendida (análisis completo, ~700-1000 palabras)."),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> Dict[str, Any]:
    detail = get_series(db, series_code)
    detail["ai_insight"] = None
    if with_ai and detail.get("observations"):
        from modules.macro_monitor.ai_context import series_ai_context
        meta = next((i for i in get_indicators(db) if i.get("series_code") == series_code), None)
        detail["ai_insight"] = _ai_insight(series_ai_context(detail, meta), "macro_trend", audience, deep)
    return detail


@router.delete(
    "/series/{series_code}",
    summary="Eliminar todas las observaciones de una serie (admin)",
    description=(
        "Solo admin. Borra de MacroSeries todas las observaciones de un "
        "series_code. Mantenimiento para códigos huérfanos que el parser dejó "
        "de producir (la ingesta hace upsert y no poda). Idempotente."
    ),
)
def delete_series_endpoint(
    series_code: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role(UserRole.admin)),
) -> Dict[str, Any]:
    deleted = delete_series(db, series_code)
    return {"series_code": series_code, "deleted": deleted}


@router.get(
    "/fiscal",
    summary="Pulso fiscal (Eje 2)",
    description="Estado de Operaciones de Hacienda (ingresos/gastos/déficit, mensual) "
    "+ recaudación por grupo de impuesto de la DGII, desde las series fiscales persistidas.",
)
def fiscal(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> Dict[str, Any]:
    return get_fiscal_pulse(db)


@router.get(
    "/fiscal/insight",
    summary="Perspectiva de IA del pulso fiscal — fase 2, lento (~10-15s)",
    description="Lectura SCQA de la situación fiscal (ingresos/gastos/déficit y "
    "recaudación) con Claude. Best-effort: cae a fallback estático sin clave.",
)
def fiscal_insight(
    audience: str = Query(
        "comite",
        description="Audiencia para orientar el insight (comite·inversionista·gobierno·empresa).",
    ),
    deep: bool = Query(False, description="Versión extendida (análisis completo, ~700-1000 palabras)."),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> Dict[str, Any]:
    from modules.macro_monitor.ai_context import fiscal_ai_context

    return {"ai_insight": _ai_insight(
        fiscal_ai_context(get_fiscal_pulse(db)), "fiscal_pulse", audience, deep)}


@router.get(
    "/snapshot",
    summary="Snapshot macro persistido",
    description="Momentum + señales del período indicado (o el último).",
)
def snapshot(
    period: Optional[str] = Query(None, description="Período (YYYY, YYYY-Qn, YYYY-MM). Si se omite, el último."),
    with_ai: bool = Query(False, description="Incluir lectura de coyuntura de IA (Claude) — fase 2, lento (~10-15s)"),
    audience: str = Query(
        "comite",
        description="Audiencia para orientar el insight (comite·inversionista·gobierno·empresa).",
    ),
    deep: bool = Query(False, description="Versión extendida (análisis completo, ~700-1000 palabras)."),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> Dict[str, Any]:
    snap = get_snapshot(db, period)
    if snap is None:
        return {"has_snapshot": False, "period": period}
    out = {
        "has_snapshot": True,
        "period": snap.period,
        "momentum": snap.momentum,
        "signals": snap.signals,
        "series_count": snap.series_count,
        "signal_count": snap.signal_count,
        "model_version": snap.model_version,
        "ai_insight": None,
    }
    if with_ai:
        from modules.macro_monitor.ai_context import snapshot_ai_context
        ctx = snapshot_ai_context(out, get_indicators(db))
        # Telón oficial: la última decisión de política monetaria (TPM) del BCRD, como
        # bloque estilo-publicación bajo 'contexto_oficial_bcrd' (el template lo consume y
        # el numeric_guard permite sus cifras). La decisión y el nivel son deterministas.
        com = com_service.comunicado_prompt_context(db)
        if com:
            cifras = []
            if com.get("tpm_nivel") is not None:
                cifras.append({"etiqueta": "TPM resultante", "valor": f"{com['tpm_nivel']}%"})
            if com.get("decision"):
                cifras.append({"etiqueta": "Decisión de la Junta Monetaria", "valor": com["decision"]})
            ctx["contexto_oficial_bcrd"] = [{
                "informe": "Comunicado de Política Monetaria del BCRD (última decisión)",
                "periodo": com.get("fecha") or "",
                "resumen": com.get("resumen", ""),
                "hallazgos": com.get("hallazgos", []),
                "cifras": cifras,
                "riesgos": com.get("riesgos", []),
                "fuente": com.get("fuente", ""),
            }]
        out["ai_insight"] = _ai_insight(ctx, "macro_snapshot", audience, deep)
    return out


@router.get(
    "/signals",
    summary="Señales de alerta temprana",
    description="Señales del snapshot (Reinhart-Rogoff deuda, Calvo freno súbito).",
)
def signals(
    period: Optional[str] = Query(None, description="Período. Si se omite, el último."),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> Dict[str, Any]:
    snap = get_snapshot(db, period)
    if snap is None:
        return {"period": period, "signals": [], "count": 0}
    sigs = snap.signals or []
    return {"period": snap.period, "signals": sigs, "count": len(sigs)}


@router.get(
    "/macro-context",
    summary="Contrato macro→sectorial (factores con impacto por sector)",
    description=(
        "Objeto estructurado del entorno macro: ~7 factores (inflación, actividad, "
        "TPM, tipo de cambio, reservas, deuda, remesas), cada uno con dirección "
        "(favorable/adverso/neutral), magnitud y los sectores/agentes que impacta. "
        "Lo consume la §2 'Contexto macro' del informe sectorial (Eje 3). Derivado "
        "del dato real del BCRD; un factor sin dato sale como 'n/d'."
    ),
)
def macro_context(
    period: Optional[str] = Query(None, description="Etiqueta del período (por defecto, el último snapshot)."),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> Dict[str, Any]:
    from modules.macro_monitor.macro_context import build_macro_context

    label = period
    if label is None:
        snap = get_snapshot(db, None)
        label = snap.period if snap is not None else None
    return build_macro_context(db, period=label).to_dict()


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
def bcrd_test(
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
def bcrd_egress_ip(
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
def bcrd_historico(
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


@router.post(
    "/backfill-historico",
    summary="Backfill del histórico BCRD (IPC + tipo de cambio)",
    description=(
        "Solo admin. Ingesta el histórico de las únicas dos series con profundidad "
        "vía API: IPC (mensual desde 1984, índice + inflación interanual derivada) y "
        "tipo de cambio (diario → mensual fin de mes). Idempotente (upsert). El resto "
        "de series son snapshot y se acumulan hacia adelante."
    ),
)
def backfill_historico_endpoint(
    year_from: int = Query(1984, description="Año inicial del backfill"),
    year_to: int = Query(2026, description="Año final del backfill"),
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role(UserRole.admin)),
) -> Dict[str, Any]:
    try:
        return backfill_historico(db, year_from=year_from, year_to=year_to)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


# ── Histórico Excel del BCRD (motor de ingesta AI-native) ─────────
@router.get(
    "/excel/catalog",
    summary="Catálogo de Excel históricos del BCRD (cobertura)",
    description=(
        "Resumen del catálogo de 708 Excel históricos del BCRD: conteo por sector y "
        "formato, más una lista cabecera de archivos de alto valor para quick-pick."
    ),
)
def excel_catalog(
    current_user: User = Depends(get_current_user),
) -> Dict[str, Any]:
    return excel_catalog_summary()


@router.post(
    "/excel/ingest",
    summary="Ingerir un Excel histórico del BCRD con el motor AI-native (admin)",
    description=(
        "Solo admin. Descarga un Excel del BCRD (por 'key' del catálogo o 'url'), "
        "infiere su estructura, extrae las series y las valida. Con 'dry_run=true' "
        "(por defecto) solo reporta qué entraría; con 'dry_run=false' hace upsert a "
        "MacroSeries (códigos bcrd.xls.*)."
    ),
)
def excel_ingest(
    key: Optional[str] = Query(None, description="Nombre de archivo del catálogo (ej. imae.xlsx)"),
    url: Optional[str] = Query(None, description="URL directa del CDN del BCRD"),
    dry_run: bool = Query(True, description="Solo reportar (true) o persistir el upsert (false)"),
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role(UserRole.admin)),
) -> Dict[str, Any]:
    if url and not url.startswith("http"):
        raise HTTPException(status_code=400, detail="La 'url' debe ser http(s) del CDN del BCRD.")
    try:
        return ingest_excel_file(db, key=key, url=url, dry_run=dry_run)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:  # noqa: BLE001 — descarga/parsing externo: reportar, no 500 opaco
        logger.warning("[macro] ingesta Excel falló: %s", e)
        raise HTTPException(status_code=502, detail=f"No se pudo ingerir el Excel: {e}")


@router.get(
    "/excel/canonical",
    summary="Registro canónico de series del BCRD (selección base-homogénea)",
    description=(
        "El set curado de ~25 series canónicas (una fuente por concepto, con base, "
        "frecuencia, estrategia de homogeneización, razón económica, robustez y la "
        "serie API ligada) + el estado de extracción actual de cada una. Documentación "
        "citable en informes."
    ),
)
def excel_canonical(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> Dict[str, Any]:
    return get_canonical_registry(db)


@router.post(
    "/excel/ingest-canonical",
    summary="Ingerir SOLO el set canónico de series del BCRD (admin)",
    description=(
        "Solo admin. Lanza en segundo plano el motor sobre los archivos canónicos "
        "(no los 708); con 'persist=true' hace upsert de las series extraídas a "
        "MacroSeries. El avance se ve en el catálogo canónico."
    ),
)
def excel_ingest_canonical(
    persist: bool = Query(False, description="Upsert de las series a MacroSeries"),
    current_user: User = Depends(require_role(UserRole.admin)),
) -> Dict[str, Any]:
    return start_canonical_ingest_background(persist=persist)


@router.get(
    "/excel/coverage",
    summary="Cobertura del corpus Excel del BCRD (reporte del barrido)",
    description=(
        "Rollup del barrido del motor sobre el catálogo: cuántos archivos se "
        "resolvieron (y por qué método/orientación/frecuencia), cuántos quedaron "
        "marcados para revisión y cuántos fallaron, con el detalle de esos."
    ),
)
def excel_coverage(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> Dict[str, Any]:
    return get_excel_coverage(db)


@router.get(
    "/excel/crosscheck",
    summary="Cruce de las series Excel contra el API del BCRD (admin)",
    description=(
        "Solo admin. Para cada serie solapada (IPC vía variación interanual, "
        "reservas), extrae el Excel con el motor y la compara mes a mes contra la "
        "serie canónica del API. La prueba más fuerte de correctitud."
    ),
)
def excel_crosscheck(
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role(UserRole.admin)),
) -> Dict[str, Any]:
    return cross_validate_excel(db)


@router.post(
    "/excel/batch",
    summary="Correr el motor sobre el catálogo Excel del BCRD (admin)",
    description=(
        "Solo admin. Lanza en segundo plano el barrido del motor sobre el catálogo "
        "(o un 'sector'). Idempotente: sin 'force' omite archivos ya reportados "
        "(reanuda). Con 'persist=true' hace upsert de las series extraídas. El "
        "avance se consulta en /excel/coverage."
    ),
)
def excel_batch(
    sector: Optional[str] = Query(None, description="Procesar solo este sector"),
    limit: Optional[int] = Query(None, description="Máximo de archivos (prueba)"),
    persist: bool = Query(False, description="Upsert de las series a MacroSeries"),
    use_claude: bool = Query(True, description="Usar el intérprete Claude en layouts difíciles"),
    force: bool = Query(False, description="Re-procesar archivos ya reportados"),
    current_user: User = Depends(require_role(UserRole.admin)),
) -> Dict[str, Any]:
    return start_excel_batch_background(
        sector=sector, limit=limit, use_claude=use_claude,
        persist_series=persist, force=force,
    )


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
def list_publications(
    report_key: Optional[str] = Query(None, description="Clave del informe (opcional)"),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> Dict[str, Any]:
    rows = pub_service.list_publications(db, report_key)
    bcrd = set(pub_catalog.report_keys("BCRD"))
    rows = [r for r in rows if r.report_key in bcrd]  # ONE studies surface in their own ejes
    return {"publications": [_pub_summary(r) for r in rows], "count": len(rows)}


@router.get(
    "/publications/catalog",
    summary="Catálogo + calendario de informes BCRD",
    description="Los informes recurrentes (cadencia, sectores, link al BCRD) y el último período ingerido de cada uno.",
)
def publications_catalog(
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
        for spec in pub_catalog.REPORTS.values() if spec.source == "BCRD"
    ]
    return {"reports": reports, "count": len(reports)}


@router.get(
    "/publications/{pub_id}",
    summary="Detalle de una publicación (con digest completo)",
)
def publication_detail(
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
def refresh_publications(
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
    keys = [report_key] if report_key else pub_catalog.report_keys("BCRD")
    results = []
    for key in keys:
        row = pub_service.ingest_report(db, key, force=force)
        if row is None:
            results.append({"report_key": key, "status": "unavailable", "period": None})
        else:
            results.append({"report_key": key, "status": row.status, "period": row.period})
    ingested = sum(1 for r in results if r["status"] == "ok")
    return {"ingested_ok": ingested, "results": results}


# ── Comunicados de política monetaria (decisiones de TPM) ──────────
def _comunicado_summary(row) -> Dict[str, Any]:
    return {
        "id": row.id,
        "article_id": row.article_id,
        "title": row.title,
        "date": row.decision_date,
        "action": row.action,           # hold | cut | hike
        "tpm_level": row.tpm_level,      # nivel resultante (%)
        "bps_change": row.bps_change,
        "source_url": row.source_url,
        "status": row.status,
    }


@router.get(
    "/comunicados",
    summary="Comunicados de política monetaria del BCRD (decisiones de TPM)",
    description="Decisiones de TPM ingeridas (sentido + nivel + digest IA), del más reciente al más antiguo.",
)
def list_comunicados(
    limit: int = Query(24, ge=1, le=100, description="Máximo de comunicados"),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> Dict[str, Any]:
    rows = com_service.list_comunicados(db, limit=limit)
    return {"comunicados": [_comunicado_summary(r) for r in rows], "count": len(rows)}


@router.get(
    "/comunicados/latest",
    summary="Última decisión de TPM del BCRD (con digest completo)",
)
def latest_comunicado(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> Dict[str, Any]:
    row = com_service.latest_comunicado(db)
    if row is None:
        return {"has_comunicado": False}
    out = _comunicado_summary(row)
    out["has_comunicado"] = True
    out["digest"] = row.digest or {}
    return out


@router.post(
    "/comunicados/refresh",
    summary="Ingerir los comunicados de política monetaria más recientes (admin)",
    description=(
        "Descubre los comunicados de TPM del BCRD, deriva la decisión (sentido + nivel) y "
        "genera el digest IA del racional. Idempotente: omite los ya ingeridos salvo 'force'."
    ),
)
def refresh_comunicados(
    limit: int = Query(12, ge=1, le=100, description="Cuántos comunicados recientes revisar"),
    force: bool = Query(False, description="Re-ingerir aunque ya existan"),
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role(UserRole.admin)),
) -> Dict[str, Any]:
    return com_service.ingest_comunicados(db, limit=limit, force=force)
