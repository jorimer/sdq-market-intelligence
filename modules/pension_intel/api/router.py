"""Pension Intel (SIPEN) — API endpoints.

prefix: /api/v1/pension-intel

F0 exposes the read-only data spine (system series, AFP catalog, per-AFP series,
latest snapshot, sync status) plus an admin-only sync trigger. Scoring and AI
insight endpoints land in F1/F2.
"""
import logging
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile
from sqlalchemy.orm import Session

from shared.auth.dependencies import get_current_user, require_role
from shared.auth.models import User, UserRole
from shared.database.session import get_db
from modules.pension_intel.models.models import (
    PensionEntity,
    PensionRating,
    PensionSeries,
    PensionSnapshot,
)

logger = logging.getLogger("sdq.api.pension_intel")

router = APIRouter()

# Audiences served by the pension pulse narrative (see cerebro AUDIENCE_FRAMES).
_AUDIENCES = {"inversionista", "regulador", "afiliado", "gobierno"}


async def _ai_insight(
    context: Dict[str, Any], audience: str = "inversionista", deep: bool = False,
    template: str = "pension_pulse",
) -> Dict[str, Any] | None:
    """Claude narrative via the cerebro route (axis=pension_intel); best-effort
    (returns None on any failure so the endpoint never breaks). Without an API key
    the engine serves a static fallback."""
    try:
        from shared.narrative.claude_engine import narrative_engine
        res = await narrative_engine.generate(
            context, template=template, mode="deep" if deep else "detailed",
            axis="pension_intel", audience=audience,
        )
        return {"text": res.text, "model_used": res.model_used, "from_cache": res.from_cache}
    except Exception as e:  # noqa: BLE001 — AI is best-effort, never break the endpoint
        logger.warning("AI insight pensiones (%s) no disponible: %s", template, e)
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


def _rating_payload(r: PensionRating, name: str) -> Dict[str, Any]:
    return {
        "slug": r.entity_slug, "name": name, "period": r.period,
        "overall_score": r.overall_score, "band": r.band, "coverage": r.coverage,
        "dimensions": r.dimensions or [], "model_version": r.model_version,
    }


def _ranked_ratings(db: Session) -> List[Dict[str, Any]]:
    names = {e.slug: e.name for e in db.query(PensionEntity).all()}
    # One rating per AFP: the latest period. A re-score at a newer statement period
    # (e.g. financials "2026-06" superseding the base "2025-04") must replace the older
    # row in the ranking, not appear twice. Period labels are "YYYY-MM" → lexical max.
    latest: Dict[str, PensionRating] = {}
    for r in db.query(PensionRating).all():
        cur = latest.get(r.entity_slug)
        if cur is None or (r.period or "") > (cur.period or ""):
            latest[r.entity_slug] = r
    payloads = [_rating_payload(r, names.get(r.entity_slug, r.entity_slug)) for r in latest.values()]
    payloads.sort(
        key=lambda p: (p["overall_score"] is not None, p["overall_score"] or 0),
        reverse=True,
    )
    for i, p in enumerate(payloads):
        p["rank"] = i + 1 if p["overall_score"] is not None else None
    return payloads


@router.get("/rankings")
async def rankings(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """AFPs ranked by the Índice de Solidez (ISA). Band index, not a credit rating."""
    payloads = _ranked_ratings(db)
    return {
        "rankings": [
            {k: p[k] for k in ("rank", "slug", "name", "overall_score", "band", "coverage", "period")}
            for p in payloads
        ],
        "count": len(payloads),
        # Relative, partial position score (0-100). Absolute bands deferred until solvency.
        "scale": "isa_relative_partial",
    }


@router.get("/entity-insight/{slug}")
async def entity_insight(
    slug: str,
    audience: str = Query("inversionista"),
    deep: bool = Query(False),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """AI narrative (Cerebro) of one AFP's ISA. Best-effort."""
    from modules.pension_intel.ai_context import pension_entity_context
    peers = _ranked_ratings(db)
    rating = next((p for p in peers if p["slug"] == slug), None)
    if rating is None:
        return {"slug": slug, "ai_insight": None}
    aud = audience if audience in _AUDIENCES else "inversionista"
    context = pension_entity_context(rating, peers)
    try:
        from shared.narrative.claude_engine import narrative_engine
        res = await narrative_engine.generate(
            context, template="pension_entity", mode="deep" if deep else "detailed",
            axis="pension_intel", audience=aud,
        )
        ai = {"text": res.text, "model_used": res.model_used, "from_cache": res.from_cache}
    except Exception as e:  # noqa: BLE001 — best-effort, never break the endpoint
        logger.warning("AI entity-insight pensiones (%s) no disponible: %s", slug, e)
        ai = None
    return {"slug": slug, "audience": aud, "ai_insight": ai}


@router.get("/{slug}/detail")
async def entity_detail(
    slug: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Full ISA breakdown for one AFP (dimensions, provenance, coverage, band)."""
    names = {e.slug: e.name for e in db.query(PensionEntity).all()}
    # Latest rating period for this AFP. A re-score at a newer statement/rentabilidad
    # period adds a fresh row (upsert is per slug+period), so the read MUST pick the
    # newest — otherwise an unordered .first() returns a stale older-period rating
    # (matches the latest-period rule in _ranked_ratings used by /rankings).
    row = (
        db.query(PensionRating)
        .filter(PensionRating.entity_slug == slug)
        .order_by(PensionRating.period.desc())
        .first()
    )
    if row is None:
        return {"slug": slug, "found": False}
    return {"found": True, **_rating_payload(row, names.get(slug, slug))}


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


@router.post("/financials/upload")
async def upload_financials(
    afp_slug: str = Form(..., description="AFP slug, p.ej. afp_popular"),
    file: UploadFile = File(..., description="Estado financiero (PDF o XLSX)"),
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role(UserRole.admin)),
):
    """Manual upload of one AFP's estados financieros (PDF/XLSX) → ingest + recompute ISA.

    The always-works path when the live sync can't get past SIPEN's bot wall. Extracts
    patrimonio/activos with the AI-native engine → activates the AFP's solvency dimension.
    """
    from modules.pension_intel.financials_sync import ingest_financials
    content = await file.read()
    try:
        result = ingest_financials(db, afp_slug, content, file.filename or "upload.pdf")
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))
    except Exception as e:  # noqa: BLE001
        logger.exception("Carga de estados financieros falló")
        raise HTTPException(status_code=500, detail=f"No se pudo procesar el archivo: {e}")
    return {"ok": True, **result}


@router.get("/financials/debug")
async def debug_financials(
    slug: str = Query(..., description="AFP slug, p.ej. afp_popular"),
    mode: str = Query("vision", description="vision | ocr — qué path de extracción usar"),
    current_user: User = Depends(require_role(UserRole.admin)),
):
    """Diagnóstico (admin, NO persiste): baja el último estado financiero de una AFP, lo
    extrae por el path elegido (visión Claude o OCR→texto→Claude) y devuelve las filas-clave
    del balance + el mapeo + un extracto del texto OCR alrededor de 'activo'. Sirve para ver
    si falta activos_totales por mapeo o por extracción, y comparar visión vs OCR (costo)."""
    import os
    import tempfile

    import httpx

    from modules.pension_intel.financials_sync import (
        _BROWSER_HEADERS, latest_statement_url,
    )
    from modules.pension_intel.external.financials_extractor import (
        map_afp_financials, statement_period,
    )
    from modules.banking_score.external.audited_pdf_extractor import (
        AuditedPdfExtractor, extract_pdf_text, render_pdf_images,
    )
    found = latest_statement_url(slug)
    if not found:
        raise HTTPException(status_code=404, detail="No se encontró estado financiero para esa AFP.")
    period, url = found
    with httpx.Client(timeout=90, headers=_BROWSER_HEADERS, follow_redirects=True) as http:
        content = http.get(url).content
    fname = url.rsplit("/", 1)[-1]

    with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as fh:
        fh.write(content)
        path = fh.name
    ocr_excerpt = None
    try:
        ex = AuditedPdfExtractor()
        if mode == "ocr":
            text = extract_pdf_text(path)
            # lines mentioning 'activo' — to judge whether a no-API parse is feasible.
            ocr_excerpt = [ln.strip() for ln in text.splitlines()
                           if "activo" in ln.lower()][:12]
            statements = ex._extract_with_fallback(text)  # noqa: SLF001 — diagnostic
        else:
            statements = ex._extract_from_images(render_pdf_images(path))  # noqa: SLF001
    except Exception as e:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=f"Extracción ({mode}) falló: {e}")
    finally:
        if os.path.exists(path):
            os.remove(path)

    bg = statements.get("balance_general") or []

    def _row(r: Dict[str, Any]) -> Dict[str, Any]:
        return {k: r.get(k) for k in
                ("original_text", "category", "subcategory", "amount_current", "is_total", "is_subtotal")}

    def _key(r: Dict[str, Any]) -> bool:
        txt = str(r.get("original_text", "")).lower()
        return bool(r.get("is_total")) or any(w in txt for w in ("activo", "pasivo", "patrimonio"))

    return {
        "slug": slug, "file": fname, "period_file": period, "mode": mode,
        "company_info": statements.get("company_info"),
        "n_balance_rows": len(bg),
        "key_rows": [_row(r) for r in bg if _key(r)],
        "ocr_activo_lines": ocr_excerpt,
        "mapped": map_afp_financials(statements),
        "statement_period": statement_period(statements),
    }


@router.post("/financials/sync")
async def trigger_financials_sync(
    current_user: User = Depends(require_role(UserRole.admin)),
):
    """Trigger the live estados-financieros sync (admin only). Runs from Railway."""
    from shared.operations.service import trigger
    return trigger("sipen-financials-sync", origin="api", user_id=current_user.id)


# ── Cartera de inversiones (portfolio composition, Cuadro 6.1 del boletín) ──────
def _holding_payload(h) -> Dict[str, Any]:
    return {
        "sub_sector": h.sub_sector, "issuer": h.issuer, "issuer_slug": h.issuer_slug,
        "amount": h.amount, "pct": h.pct, "is_subtotal": h.is_subtotal,
        "macro_class": h.macro_class, "bank_entity_slug": h.bank_entity_slug,
    }


def _build_cartera(db: Session, period: Optional[str], fund: str) -> Dict[str, Any]:
    """Portfolio composition payload (Cuadro 6.1) for a fund/period. Latest if period=None."""
    from modules.pension_intel.models.models import PensionHolding

    q = db.query(PensionHolding).filter(PensionHolding.fund == fund)
    if period is None:
        latest = q.order_by(PensionHolding.period.desc()).first()
        if latest is None:
            return {"found": False, "fund": fund, "holdings": []}
        period = latest.period
    rows = (q.filter(PensionHolding.period == period)
            .order_by(PensionHolding.amount.desc().nullslast()).all())
    if not rows:
        return {"found": False, "fund": fund, "period": period, "holdings": []}

    leaves = [r for r in rows if not r.is_subtotal]
    total = sum(r.amount for r in leaves if r.amount is not None)

    def _class_total(macro_class: str) -> float:
        return sum(r.amount for r in leaves
                   if r.macro_class == macro_class and r.amount is not None)

    public_debt = _class_total("deuda_publica")
    bcrd = _class_total("bcrd")
    return {
        "found": True, "fund": fund, "period": period,
        "total": total,
        "summary": {
            "public_debt_amount": public_debt,
            "public_debt_pct": round(public_debt / total * 100, 2) if total else None,
            "bcrd_amount": bcrd,
            "bcrd_pct": round(bcrd / total * 100, 2) if total else None,
            "issuer_count": len(leaves),
        },
        "holdings": [_holding_payload(r) for r in rows],
    }


@router.get("/cartera")
async def cartera(
    period: Optional[str] = Query(None, description="Trimestre, p.ej. 2026-Q1 (por defecto el último)"),
    fund: str = Query("cci", description="Fondo (cci)"),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Composición de la cartera de inversiones de los fondos por emisor (Cuadro 6.1).

    Devuelve las tenencias (emisores + subtotales por sub-sector) del fondo y período, más
    un resumen con las concentraciones clave (deuda pública / BCRD). Sin período → el último."""
    return _build_cartera(db, period, fund)


@router.get("/cartera/insight")
async def cartera_insight(
    audience: str = Query("inversionista"),
    deep: bool = Query(False),
    period: Optional[str] = Query(None),
    fund: str = Query("cci"),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """AI narrative (Cerebro) over the portfolio composition. Best-effort."""
    from modules.pension_intel.ai_context import pension_cartera_context
    data = _build_cartera(db, period, fund)
    if not data.get("found"):
        return {"audience": audience, "ai_insight": None}
    aud = audience if audience in _AUDIENCES else "inversionista"
    context = pension_cartera_context(data)
    try:
        from shared.narrative.claude_engine import narrative_engine
        res = await narrative_engine.generate(
            context, template="pension_cartera", mode="deep" if deep else "detailed",
            axis="pension_intel", audience=aud,
        )
        ai = {"text": res.text, "model_used": res.model_used, "from_cache": res.from_cache}
    except Exception as e:  # noqa: BLE001 — best-effort, never break the endpoint
        logger.warning("AI insight cartera no disponible: %s", e)
        ai = None
    return {"audience": aud, "ai_insight": ai}


@router.post("/cartera/upload")
async def upload_cartera(
    file: UploadFile = File(..., description="Boletín Trimestral SIPEN (PDF)"),
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role(UserRole.admin)),
):
    """Carga manual de un Boletín Trimestral (PDF) → extrae el Cuadro 6.1 → persiste cartera."""
    from modules.pension_intel.cartera_sync import ingest_cartera
    from modules.pension_intel.external.cartera_extractor import CarteraExtractionError
    content = await file.read()
    try:
        result = ingest_cartera(db, content, file.filename or "boletin.pdf")
    except CarteraExtractionError as e:
        raise HTTPException(status_code=422, detail=str(e))
    except Exception as e:  # noqa: BLE001
        logger.exception("Carga de boletín (cartera) falló")
        raise HTTPException(status_code=500, detail=f"No se pudo procesar el boletín: {e}")
    return {"ok": True, **result}


@router.post("/cartera/sync")
async def trigger_cartera_sync(
    current_user: User = Depends(require_role(UserRole.admin)),
):
    """Trigger the live cartera sync (admin only). Discovers the latest bulletin on SIPEN."""
    from shared.operations.service import trigger
    return trigger("sipen-cartera-sync", origin="api", user_id=current_user.id)


# ── Drill-down por indicador (estilo banca: detalle + tendencia + pares + insight IA) ──
# Two-phase: el frontend pide con ?with_ai=false el detalle instantáneo (valor/tendencia/
# pares) y luego con ?with_ai=true la narrativa Cerebro de ESE indicador/dimensión/posición.

# Etiquetas legibles de los indicadores del sistema (para el contexto IA; la UI i18n por code).
_SYSTEM_INDICATORS: Dict[str, str] = {
    "sipen.rentabilidad.cci_nominal_anual": "Rentabilidad nominal CCI",
    "sipen.rentabilidad.sdp_nominal_anual": "Rentabilidad nominal del sistema (SDP)",
    "sipen.comisiones.total_anual": "Comisiones del sistema",
    "sipen.afiliados.total": "Afiliados",
    "sipen.cotizantes.total": "Cotizantes",
    "sipen.salario_minimo_cotizable": "Salario mínimo cotizable",
    "sipen.patrimonio.crecimiento_anual": "Crecimiento del patrimonio",
}
# AFP dimension key → the per-AFP PensionSeries metric whose history is the trend (ratio
# dims have no single series → no trend line).
_DIM_TREND_METRIC: Dict[str, str] = {
    "rentabilidad": "rentabilidad_nominal_anual",
    "escala": "fondos_administrados",
}


@router.get("/indicator")
async def system_indicator(
    code: str = Query(..., description="Código de serie del sistema, p.ej. sipen.rentabilidad.cci_nominal_anual"),
    with_ai: bool = Query(False),
    audience: str = Query("inversionista"),
    deep: bool = Query(False),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Drill-down de UN indicador del sistema: nivel actual + tendencia + insight IA propio."""
    rows = (db.query(PensionSeries)
            .filter(PensionSeries.entity_slug.is_(None), PensionSeries.series_code == code,
                    PensionSeries.value.isnot(None))
            .order_by(PensionSeries.period.asc()).all())
    if not rows:
        return {"found": False, "code": code}
    points = [(r.period, r.value) for r in rows]
    label = _SYSTEM_INDICATORS.get(code, code)
    unit = rows[-1].unit
    ai = None
    if with_ai:
        from modules.pension_intel.ai_context import pension_indicator_context
        aud = audience if audience in _AUDIENCES else "inversionista"
        ai = await _ai_insight(pension_indicator_context(code, label, unit, points),
                               audience=aud, deep=deep, template="pension_system_indicator")
    return {
        "found": True, "code": code, "label": label, "unit": unit,
        "latest": {"value": points[-1][1], "period": points[-1][0]},
        "trend": [{"period": p, "value": v} for p, v in points],
        "ai_insight": ai,
    }


@router.get("/{slug}/dimension")
async def afp_dimension(
    slug: str,
    key: str = Query(..., description="Dimensión del ISA: solvencia | rentabilidad | escala | costo"),
    with_ai: bool = Query(False),
    audience: str = Query("inversionista"),
    deep: bool = Query(False),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Drill-down de UNA dimensión del ISA de una AFP: valor + posición vs pares + tendencia + insight IA."""
    from modules.pension_intel.scoring.isa import compute_isa
    results = compute_isa(db)
    me = next((r for r in results if r["slug"] == slug), None)
    if me is None:
        return {"found": False, "slug": slug}
    dim = next((d for d in me["dimensions"] if d["key"] == key), None)
    if dim is None:
        return {"found": False, "slug": slug, "key": key}
    peers = [{"afp": r["name"],
              "raw": next((d["raw"] for d in r["dimensions"] if d["key"] == key), None),
              "score": next((d["score"] for d in r["dimensions"] if d["key"] == key), None)}
             for r in results]
    trend: List = []
    metric = _DIM_TREND_METRIC.get(key)
    if metric:
        trows = (db.query(PensionSeries)
                 .filter(PensionSeries.entity_slug == slug, PensionSeries.series_code == metric,
                         PensionSeries.value.isnot(None))
                 .order_by(PensionSeries.period.asc()).all())
        trend = [(r.period, r.value) for r in trows]
    ai = None
    if with_ai and dim["present"]:
        from modules.pension_intel.ai_context import pension_dimension_context
        aud = audience if audience in _AUDIENCES else "inversionista"
        ai = await _ai_insight(pension_dimension_context(me["name"], dim, peers, trend),
                               audience=aud, deep=deep, template="pension_afp_dimension")
    return {
        "found": True, "slug": slug, "afp": me["name"], "period": me["period"],
        "dimension": dim,
        "peers": peers,
        "trend": [{"period": p, "value": v} for p, v in trend],
        "ai_insight": ai,
    }


@router.get("/cartera/holding")
async def cartera_holding(
    issuer_slug: str = Query(..., description="issuer_slug de la posición de cartera"),
    period: Optional[str] = Query(None),
    fund: str = Query("cci"),
    with_ai: bool = Query(False),
    audience: str = Query("inversionista"),
    deep: bool = Query(False),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Drill-down de UNA posición de la cartera (emisor o sub-sector): peso + naturaleza + insight IA."""
    data = _build_cartera(db, period, fund)
    if not data.get("found"):
        return {"found": False, "issuer_slug": issuer_slug}
    h = next((x for x in data["holdings"] if x["issuer_slug"] == issuer_slug), None)
    if h is None:
        return {"found": False, "issuer_slug": issuer_slug, "period": data["period"]}
    ai = None
    if with_ai:
        from modules.pension_intel.ai_context import pension_cartera_item_context
        aud = audience if audience in _AUDIENCES else "inversionista"
        ai = await _ai_insight(pension_cartera_item_context(h, data["total"], data["period"]),
                               audience=aud, deep=deep, template="pension_cartera_item")
    return {
        "found": True, "period": data["period"], "fund": fund,
        "total": data["total"], "holding": h, "ai_insight": ai,
    }
