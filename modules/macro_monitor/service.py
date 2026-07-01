"""Macro Monitor — ingestion, snapshot computation, persistence & events.

Pipeline:
    1. ingest_series: pull records from a shared/data source → upsert MacroSeries.
    2. build_snapshot: compute per-series momentum + early-warning signals,
       persist a MacroSnapshot and publish ``macro.updated``.

The scoring (`scoring/momentum.py`, `scoring/signals.py`) is pure; this layer
wires it to the DB, the data layer and the event bus.
"""
import logging
import re
from calendar import monthrange
from collections import defaultdict
from datetime import date
from typing import Any, Dict, List, Optional

from sqlalchemy.orm import Session

from shared.data.base_client import SourceClient
from shared.data.bcrd_client import bcrd_client, resolve_bcrd_client, series_label
from modules.macro_monitor.events import publish_macro_updated
from modules.macro_monitor.models.models import MacroSeries, MacroSnapshot
from modules.macro_monitor.scoring.momentum import compute_series_momentum
from modules.macro_monitor.scoring.signals import detect_signals

logger = logging.getLogger("sdq.macro_monitor.service")

MODEL_VERSION = "1.0"

# Series used by the early-warning signals.
DEBT_SERIES = "public_debt_gdp"
FLOW_SERIES = {"remittances", "fdi", "reserves", "exports", "capital_flows"}


def _upsert_records(db: Session, records) -> int:
    """Upsert a list of :class:`Record` into MacroSeries (by series_code+period).

    Dedupes the batch by (series_code, period) first: the Excel extractor can emit
    duplicate rows for some flagged layouts, and the session is ``autoflush=False``,
    so two same-key rows both pass the per-row "not found" check and then collide at
    commit (Postgres UniqueViolation on uq_mm_series_period). Last-wins matches the
    per-row upsert semantics.
    """
    deduped: Dict[tuple, Any] = {}
    for r in records:
        deduped[(r.series, r.period)] = r
    records = list(deduped.values())
    touched = 0
    for r in records:
        row = (
            db.query(MacroSeries)
            .filter_by(series_code=r.series, period=r.period)
            .first()
        )
        lic = r.lineage.license if r.lineage else None
        pub = r.lineage.published_at if r.lineage else None
        src = r.lineage.source if r.lineage else None
        if row is None:
            db.add(MacroSeries(
                series_code=r.series, period=r.period, value=r.value,
                unit=r.unit, source=src, published_at=pub, license=lic,
            ))
        else:
            row.value = r.value
            row.unit = r.unit
            row.source = src
            row.published_at = pub
            row.license = lic
        touched += 1
    db.commit()
    return touched


def ingest_series(db: Session, client: Optional[SourceClient] = None) -> int:
    """Upsert observations from *client* into MacroSeries.  Returns rows touched.

    When *client* is omitted, resolves the BCRD source: live API if a token is
    configured+enabled (Configuración → BCRD), otherwise the local fixture.
    """
    if client is None:
        client = resolve_bcrd_client(db)
    touched = _upsert_records(db, client.fetch())
    logger.info("Ingesta macro: %d observaciones (%s)", touched, client.source)
    return touched


# Fiscal pulse (Eje 2): the DGII + Hacienda connectors emit one ``series`` name with
# the actual line in ``dimension``; remap to a namespaced ``series_code`` so each
# fiscal line is its own MacroSeries (no collision under the (series_code, period) key).
FISCAL_SOURCES = (
    ("fiscal_eo", "Estado de Operaciones (Hacienda)"),    # ingresos/gastos/déficit, mensual
    ("fiscal_dgii", "recaudación por impuesto (DGII)"),   # recaudación efectiva, mensual
)


def fiscal_sync(db: Session, set_phase: Optional[Any] = None,
                clients: Optional[Dict[str, SourceClient]] = None) -> Dict[str, Any]:
    """Pull the fiscal pulse (Hacienda Estado de Operaciones + DGII recaudación) and
    upsert it into MacroSeries as namespaced fiscal series. Best-effort per source.

    *clients* lets tests inject fixture-mode clients; live otherwise.
    """
    from dataclasses import replace

    set_phase = set_phase or (lambda _m: None)
    if clients is None:
        from shared.data.dgii_client import DGIIClient
        from shared.data.hacienda_client import HaciendaClient
        clients = {"fiscal_eo": HaciendaClient(mode="live"), "fiscal_dgii": DGIIClient(mode="live")}

    touched = 0
    codes: set = set()
    periods: set = set()
    errors: List[str] = []
    for prefix, label in FISCAL_SOURCES:
        set_phase(f"descargando {label}")
        try:
            records = list(clients[prefix].fetch())
        except Exception as e:  # noqa: BLE001 — best-effort; report, don't crash the op
            logger.warning("fiscal sync %s falló: %s", prefix, e)
            errors.append(f"{label}: {e}")
            continue
        remapped = [replace(r, series=f"{prefix}.{r.dimension}") for r in records if r.dimension]
        touched += _upsert_records(db, remapped)
        codes |= {r.series for r in remapped}
        periods |= {r.period for r in remapped}
    return {"touched": touched, "series": len(codes), "errors": errors,
            "period_range": [min(periods), max(periods)] if periods else None}


# Display labels for the fiscal lines (Estado de Operaciones + DGII recaudación).
FISCAL_LABELS = {
    "ingresos": "Ingresos", "gastos": "Gastos", "balance_global": "Balance global (déficit)",
    "resultado_operativo": "Resultado operativo", "impuestos": "Impuestos",
    "imp_ingresos": "Imp. sobre ingresos", "imp_propiedad": "Imp. sobre propiedad",
    "imp_bienes_servicios": "Imp. bienes y servicios (ITBIS)",
    "imp_comercio_exterior": "Imp. comercio exterior", "contribuciones_sociales": "Contribuciones sociales",
    "otros_ingresos": "Otros ingresos", "remuneracion": "Remuneración", "intereses": "Intereses",
    "subsidios": "Subsidios", "inversion": "Inversión",
    "comercio_exterior": "Comercio exterior", "mercancias_servicios": "Mercancías y servicios",
    "ecologicos": "Ecológicos", "contraprestacion": "Contraprestación", "otros": "Otros", "propiedad": "Propiedad",
}
# EO lines surfaced as the monthly fiscal timeline.
_EO_TIMELINE = ("ingresos", "gastos", "balance_global")


def get_fiscal_pulse(db: Session) -> Dict[str, Any]:
    """Assemble the fiscal pulse for the macro UI from the persisted fiscal series.

    Returns the EO monthly timeline (ingresos / gastos / balance global) and the
    latest DGII recaudación composition by tax group. ``has_data`` False if the
    fiscal-sync hasn't run. Mixed units are flagged per panel (EO in RD$ millones,
    DGII in RD$)."""
    rows = (db.query(MacroSeries)
            .filter(MacroSeries.series_code.like("fiscal_%")).all())
    by_code: Dict[str, Dict[str, float]] = defaultdict(dict)
    for r in rows:
        if r.value is not None and r.period:
            by_code[r.series_code][r.period] = r.value
    if not by_code:
        return {"has_data": False}

    def timeline(code: str) -> List[Dict[str, Any]]:
        d = by_code.get(f"fiscal_eo.{code}", {})
        return [{"period": p, "value": d[p]} for p in sorted(d)]

    eo = {k: timeline(k) for k in _EO_TIMELINE}
    latest = eo["ingresos"][-1]["period"] if eo["ingresos"] else None
    eo_latest = {k: (by_code.get(f"fiscal_eo.{k}", {}).get(latest)) for k in _EO_TIMELINE} if latest else {}

    # DGII recaudación composition for its latest month (the tax groups, not the total)
    dgii_codes = [c for c in by_code if c.startswith("fiscal_dgii.") and not c.endswith(".total")]
    dgii_periods = sorted({p for c in dgii_codes for p in by_code[c]})
    dgii_latest = dgii_periods[-1] if dgii_periods else None
    recaudacion = []
    for c in dgii_codes:
        slug = c.split(".", 1)[1]
        v = by_code[c].get(dgii_latest)
        if v is not None:
            recaudacion.append({"slug": slug, "label": FISCAL_LABELS.get(slug, slug), "value": v})
    recaudacion.sort(key=lambda x: x["value"], reverse=True)

    all_periods = sorted({p for d in by_code.values() for p in d})
    return {
        "has_data": True,
        "period_range": [all_periods[0], all_periods[-1]],
        "latest_period": latest,
        "eo_unit": "RD$ millones",
        "eo": eo,
        "eo_latest": eo_latest,
        "recaudacion_unit": "RD$",
        "recaudacion": {"period": dgii_latest, "groups": recaudacion},
    }


def backfill_historico(db: Session, year_from: int = 1984, year_to: int = 2026) -> Dict[str, Any]:
    """One-time backfill of the BCRD historical series (IPC + exchange rates).

    Only these two have history via the API (the rest are snapshot-only). Requires
    a configured+enabled BCRD token. Returns the rows touched and the span found.
    """
    from shared.data.bcrd_api import BCRD_BASE_URL
    from shared.data.bcrd_client import fetch_history
    from shared.settings.service import get_sector_api_base_url, get_sector_api_key

    token = get_sector_api_key(db, "bcrd")
    if not token:
        raise ValueError("Falta el token del BCRD o la fuente está deshabilitada.")
    base = get_sector_api_base_url(db, "bcrd") or BCRD_BASE_URL
    records = fetch_history(token, base, year_from, year_to)
    touched = _upsert_records(db, records)
    periods = sorted({r.period for r in records})
    by_series: Dict[str, int] = {}
    for r in records:
        by_series[r.series] = by_series.get(r.series, 0) + 1
    logger.info("Backfill histórico BCRD: %d observaciones, %d series", touched, len(by_series))
    return {
        "touched": touched,
        "series": by_series,
        "period_min": periods[0] if periods else None,
        "period_max": periods[-1] if periods else None,
    }


# ── Histórico Excel del BCRD (motor de ingesta AI-native) ─────────
# Catálogo cabecera: los archivos de mayor valor, para quick-pick en la UI. Se
# filtran contra el catálogo real (algunos pueden no estar presentes).
_EXCEL_FEATURED = [
    ("imae.xlsx", "IMAE — actividad económica"),
    ("ipc.xls", "IPC — índice de precios"),
    ("reservas_internacionales.xlsx", "Reservas internacionales"),
    ("agregados_monetarios.xlsx", "Agregados monetarios (M1, M2…)"),
    ("base_monetaria.xlsx", "Base monetaria"),
    ("Serie_TPM.xlsx", "Tasa de Política Monetaria"),
    ("Remesas_6.xlsx", "Remesas"),
    ("bpagos.xls", "Balanza de pagos"),
]


def excel_catalog_summary() -> Dict[str, Any]:
    """Resumen del catálogo de Excel históricos del BCRD (708 archivos) para la UI."""
    from shared.data.bcrd_excel.catalog import find_entry, load_catalog

    entries = load_catalog()
    by_sector: Dict[str, int] = {}
    by_ext: Dict[str, int] = {}
    for e in entries:
        by_sector[e.sector] = by_sector.get(e.sector, 0) + 1
        by_ext[e.ext] = by_ext.get(e.ext, 0) + 1
    featured = []
    for filename, label in _EXCEL_FEATURED:
        entry = find_entry(filename)
        if entry is not None:
            featured.append({"key": entry.filename, "label": label,
                             "sector": entry.sector, "ext": entry.ext, "url": entry.url})
    return {
        "total": len(entries),
        "by_sector": by_sector,
        "by_ext": by_ext,
        "featured": featured,
    }


def ingest_excel_file(
    db: Session, *, key: Optional[str] = None, url: Optional[str] = None,
    dry_run: bool = True,
) -> Dict[str, Any]:
    """Corre el motor sobre UN Excel del BCRD: descarga → spec → extracción →
    validación; si ``dry_run`` es False, hace upsert a MacroSeries.

    *key* es un nombre de archivo del catálogo (resuelve la URL del CDN); *url* es
    una URL/ruta directa. Devuelve el resumen + las series extraídas con su estado
    de validación, para que la UI muestre exactamente qué entraría/entró.
    """
    from shared.data.bcrd_excel.catalog import find_entry
    from shared.data.bcrd_excel.engine import SpecCache, ingest_excel

    source: Any
    if key:
        entry = find_entry(key)
        if entry is None:
            raise ValueError(f"El archivo '{key}' no está en el catálogo del BCRD.")
        source = entry
    elif url:
        source = url
    else:
        raise ValueError("Indica 'key' (archivo del catálogo) o 'url'.")

    result = ingest_excel(source, cache=SpecCache())
    touched = 0
    if not dry_run:
        touched = _upsert_records(db, result.records)
        logger.info("[macro] ingesta Excel %s: %d observaciones upserted", result.file, touched)

    series_rows = [
        {
            "code": s.code, "unit": s.unit, "n_obs": s.n_obs,
            "n_missing": s.n_missing, "period_min": s.period_min,
            "period_max": s.period_max, "ok": s.ok, "flags": s.flags,
        }
        for s in result.report.series
    ]
    return {
        "file": result.file,
        "method": result.spec.method,
        "confidence": result.spec.confidence,
        "orientation": result.spec.orientation,
        "records": len(result.records),
        "series_count": len(result.report.series),
        "validation_ok": result.report.ok,
        "series": series_rows,
        "dry_run": dry_run,
        "touched": touched,
    }


# ── Batch run over the catalog + coverage report ──────────────────
# In-process status (mirrors the SIB sync). Survives within a web process; the
# persisted ExcelFileReport rows are the durable record across restarts.
_excel_batch_status: Dict[str, Any] = {
    "is_running": False, "done": 0, "total": 0, "started_at": None, "last_error": None,
}


def excel_batch_status() -> Dict[str, Any]:
    return dict(_excel_batch_status)


def _upsert_excel_report(db: Session, fields: Dict[str, Any]) -> None:
    from modules.macro_monitor.models.models import ExcelFileReport

    row = db.query(ExcelFileReport).filter_by(file_url=fields["file_url"]).first()
    if row is None:
        row = ExcelFileReport(file_url=fields["file_url"])
        db.add(row)
    for k, v in fields.items():
        setattr(row, k, v)
    db.commit()


def run_excel_batch(
    db: Session, *, sector: Optional[str] = None, limit: Optional[int] = None,
    use_claude: bool = True, persist_series: bool = False, force: bool = False,
) -> Dict[str, Any]:
    """Run the engine over the catalog (or one *sector*), upserting a per-file
    report. Idempotent: without *force*, files already reported are skipped
    (resume). With *persist_series*, also upserts the extracted records.
    """
    from modules.macro_monitor.models.models import ExcelFileReport
    from shared.data.bcrd_excel.catalog import load_catalog
    from shared.data.bcrd_excel.engine import SpecCache, ingest_excel

    entries = [e for e in load_catalog() if not sector or e.sector == sector]
    if limit:
        entries = entries[:limit]
    done_urls = set()
    if not force:
        # Resume: skip files already resolved (ok/flagged), but RETRY failures so a
        # fixed engine bug or a transient download error gets re-attempted.
        done_urls = {
            r.file_url
            for r in db.query(ExcelFileReport.file_url)
            .filter(ExcelFileReport.status != "failed")
            .all()
        }

    cache = SpecCache()
    _excel_batch_status.update(is_running=True, done=0, total=len(entries), last_error=None)
    ok = flagged = failed = 0
    try:
        for e in entries:
            if e.url in done_urls:
                _excel_batch_status["done"] += 1
                continue
            try:
                r = ingest_excel(e, cache=cache, use_claude=use_claude)
                status = "ok" if r.report.ok else "flagged"
                persisted = _upsert_records(db, r.records) if persist_series else 0
                _upsert_excel_report(db, {
                    "file_url": e.url, "filename": e.filename, "sector": e.sector,
                    "status": status, "method": r.spec.method,
                    "orientation": r.spec.orientation, "frequency": r.spec.frequency,
                    "confidence": r.spec.confidence, "n_records": len(r.records),
                    "n_series": len(r.report.series), "n_flagged": len(r.report.flagged),
                    "persisted": persisted, "error": None,
                    "flags": [{"code": s.code, "flags": s.flags} for s in r.report.flagged][:20],
                })
                ok += status == "ok"
                flagged += status == "flagged"
            except Exception as ex:  # noqa: BLE001 — record the failure, continue the batch
                # A failed upsert (e.g. a DB constraint) leaves the session in a
                # poisoned transaction; roll back before the next DB write, or the
                # failure-report write below ALSO throws and aborts the whole batch.
                db.rollback()
                failed += 1
                _upsert_excel_report(db, {
                    "file_url": e.url, "filename": e.filename, "sector": e.sector,
                    "status": "failed", "error": str(ex)[:500],
                })
            _excel_batch_status["done"] += 1
    finally:
        _excel_batch_status["is_running"] = False
    logger.info("[macro] batch Excel: %d ok, %d marcados, %d fallidos", ok, flagged, failed)
    return {"processed": len(entries), "ok": ok, "flagged": flagged, "failed": failed}


def get_canonical_registry(db: Session) -> Dict[str, Any]:
    """The curated canonical series + each one's current extraction status.

    The registry is the base-homogeneous selection an analyst cites; we attach the
    latest extraction outcome (from the per-file reports) so the UI can show, per
    series, whether it extracts cleanly today.
    """
    from modules.macro_monitor.models.models import ExcelFileReport
    from shared.data.bcrd_excel import canonical

    reports = {r.filename: r for r in db.query(ExcelFileReport).all()}
    out = []
    for s in canonical.as_dicts():
        rep = reports.get(s["source_file"])
        s["extraction"] = (
            {"status": rep.status, "n_series": int(rep.n_series or 0),
             "method": rep.method, "orientation": rep.orientation}
            if rep else None
        )
        out.append(s)
    return {"series": out, "count": len(out)}


def ingest_canonical(db: Session, *, persist: bool = False) -> Dict[str, Any]:
    """Run the engine over ONLY the canonical source files (not the whole catalog).

    Dedupes shared source files (e.g. reserves brutas/netas come from one file).
    Upserts a per-file report; with *persist*, upserts the extracted series too.
    """
    from shared.data.bcrd_excel import canonical
    from shared.data.bcrd_excel.catalog import find_entry
    from shared.data.bcrd_excel.engine import SpecCache, ingest_excel

    cache = SpecCache()
    seen: set = set()
    ok = flagged = failed = 0
    for s in canonical.registry():
        if s.source_file in seen:
            continue
        seen.add(s.source_file)
        entry = find_entry(s.source_file)
        if entry is None:
            failed += 1
            continue
        try:
            r = ingest_excel(entry, cache=cache, use_claude=True)
            status = "ok" if r.report.ok else "flagged"
            persisted = _upsert_records(db, r.records) if persist else 0
            _upsert_excel_report(db, {
                "file_url": entry.url, "filename": entry.filename, "sector": entry.sector,
                "status": status, "method": r.spec.method, "orientation": r.spec.orientation,
                "frequency": r.spec.frequency, "confidence": r.spec.confidence,
                "n_records": len(r.records), "n_series": len(r.report.series),
                "n_flagged": len(r.report.flagged), "persisted": persisted, "error": None,
                "flags": [{"code": x.code, "flags": x.flags} for x in r.report.flagged][:20],
            })
            ok += status == "ok"
            flagged += status == "flagged"
        except Exception as e:  # noqa: BLE001
            # Roll back the poisoned transaction (e.g. a failed upsert) before the
            # failure-report write, or it throws too and aborts the whole canonical
            # run — leaving only the files persisted before the first bad one.
            db.rollback()
            failed += 1
            _upsert_excel_report(db, {
                "file_url": entry.url, "filename": entry.filename, "sector": entry.sector,
                "status": "failed", "error": str(e)[:500],
            })
    logger.info("[macro] ingesta canónica: %d ok, %d marcados, %d fallidos", ok, flagged, failed)
    return {"files": len(seen), "ok": ok, "flagged": flagged, "failed": failed}


def start_canonical_ingest_background(*, persist: bool = False) -> Dict[str, Any]:
    """Launch the canonical ingest in the worker/thread — it runs the engine over
    ~20 files (some via Claude), too long for a synchronous request."""
    import threading

    from shared.config.settings import settings

    msg = ("Ingesta del set canónico iniciada en segundo plano (≈1-2 min). El estado "
           "de cada serie se actualiza en el catálogo canónico al recargar.")
    if settings.USE_CELERY and settings.REDIS_URL:
        try:
            from modules.macro_monitor.tasks import ingest_canonical_task
            ingest_canonical_task.delay(persist=persist)
            return {"status": "started", "via": "celery", "message": msg}
        except Exception:  # noqa: BLE001
            logger.exception("No se pudo encolar la ingesta canónica; usando hilo")

    def _run() -> None:
        from shared.database.session import SessionLocal
        db = SessionLocal()
        try:
            ingest_canonical(db, persist=persist)
        finally:
            db.close()

    threading.Thread(target=_run, daemon=True).start()
    return {"status": "started", "via": "thread", "message": msg}


def cross_validate_excel(db: Session) -> Dict[str, Any]:
    """Cross-check the Excel-extracted series against the live API series.

    For each curated mapping: extract the Excel file with the engine, apply the
    transform (identity / YoY), pull the canonical series from MacroSeries, and
    compare over the overlapping periods. The strongest correctness signal — the
    engine's figures must equal the BCRD API's.
    """
    from shared.data.bcrd_excel.catalog import find_entry
    from shared.data.bcrd_excel.crosscheck import CROSSCHECK_SPECS, compare, yoy
    from shared.data.bcrd_excel.engine import SpecCache, ingest_excel

    cache = SpecCache()
    results: List[Dict[str, Any]] = []
    for spec in CROSSCHECK_SPECS:
        try:
            entry = find_entry(spec.excel_key)
            if entry is None:
                results.append({"label": spec.label, "error": f"'{spec.excel_key}' no está en el catálogo"})
                continue
            res = ingest_excel(entry, cache=cache, use_claude=False)
            excel_vals: Dict[str, Any] = {
                r.period: r.value for r in res.records
                if r.series.endswith(spec.excel_series_suffix)
            }
            if not excel_vals:
                results.append({"label": spec.label, "error": "serie no encontrada en el Excel"})
                continue
            if spec.transform == "yoy":
                excel_vals = yoy(excel_vals)
            api_vals = {
                row.period: row.value
                for row in db.query(MacroSeries).filter_by(series_code=spec.api_series).all()
            }
            cmp = compare(excel_vals, api_vals, rel_tol=spec.rel_tol, abs_tol=spec.abs_tol)
            results.append({
                "label": spec.label, "api_series": spec.api_series,
                "transform": spec.transform, "note": spec.note,
                "n_compared": cmp.n_compared, "n_match": cmp.n_match,
                "n_mismatch": cmp.n_mismatch, "max_abs_err": cmp.max_abs_err,
                "period_min": cmp.period_min, "period_max": cmp.period_max,
                "ok": cmp.ok, "examples": cmp.examples,
                "api_obs": len(api_vals),
            })
        except Exception as e:  # noqa: BLE001 — report per-spec, don't abort the rest
            logger.warning("[macro] cross-check %s falló: %s", spec.label, e)
            results.append({"label": spec.label, "error": str(e)[:300]})
    n_ok = sum(1 for r in results if r.get("ok"))
    return {"results": results, "checks": len(results), "ok": n_ok}


def get_excel_coverage(db: Session) -> Dict[str, Any]:
    """Coverage rollup + the flagged/failed files (for the report UI)."""
    from collections import Counter

    from modules.macro_monitor.models.models import ExcelFileReport
    from shared.data.bcrd_excel.catalog import load_catalog

    total_catalog = len(load_catalog())
    rows = db.query(ExcelFileReport).all()
    by_status: Counter = Counter(r.status for r in rows)
    by_method: Counter = Counter(r.method for r in rows if r.method)
    by_freq: Counter = Counter(r.frequency for r in rows if r.frequency)
    attention = [
        {
            "filename": r.filename, "sector": r.sector, "status": r.status,
            "orientation": r.orientation, "frequency": r.frequency,
            "confidence": r.confidence, "n_series": int(r.n_series or 0),
            "n_flagged": int(r.n_flagged or 0), "error": r.error,
            "flags": r.flags or [],
        }
        for r in rows if r.status in ("flagged", "failed")
    ]
    return {
        "total_catalog": total_catalog,
        "reported": len(rows),
        "by_status": dict(by_status),
        "by_method": dict(by_method),
        "by_frequency": dict(by_freq),
        "attention": attention,
        "status": excel_batch_status(),
    }


def start_excel_batch_background(
    *, sector: Optional[str] = None, limit: Optional[int] = None,
    use_claude: bool = True, persist_series: bool = False, force: bool = False,
) -> Dict[str, Any]:
    """Launch the batch in the Celery worker (survives web restarts) or a thread."""
    import threading

    from shared.config.settings import settings

    if _excel_batch_status.get("is_running"):
        return {"status": "already_running", "message": "Ya hay un barrido en progreso."}
    msg = ("Barrido del corpus Excel iniciado en segundo plano. Puede tardar varios "
           "minutos (descarga + inferencia, con Claude en los layouts difíciles); el "
           "avance se actualiza en esta pantalla.")
    kwargs = dict(sector=sector, limit=limit, use_claude=use_claude,
                  persist_series=persist_series, force=force)
    if settings.USE_CELERY and settings.REDIS_URL:
        try:
            from modules.macro_monitor.tasks import excel_batch_task
            excel_batch_task.delay(**kwargs)
            return {"status": "started", "via": "celery", "message": msg}
        except Exception:  # noqa: BLE001 — fall back to a thread if the broker is down
            logger.exception("No se pudo encolar el batch Excel; usando hilo")

    def _run() -> None:
        from shared.database.session import SessionLocal
        db = SessionLocal()
        try:
            run_excel_batch(db, **kwargs)
        finally:
            db.close()

    threading.Thread(target=_run, daemon=True).start()
    return {"status": "started", "via": "thread", "message": msg}


_Q_END = {1: (3, 31), 2: (6, 30), 3: (9, 30), 4: (12, 31)}
_Q_START = {1: (1, 1), 2: (4, 1), 3: (7, 1), 4: (10, 1)}


def period_end_date(period: Optional[str]) -> Optional[date]:
    """Date a period label CLOSES on, for chronological ordering.

    Handles ``YYYY``, ``YYYY-MM`` and ``YYYY-Qn`` (case-insensitive). Returns
    None when unparseable, so callers can decide how to treat it.
    """
    if not period:
        return None
    p = period.strip().upper()
    m = re.fullmatch(r"(\d{4})", p)
    if m:
        return date(int(m.group(1)), 12, 31)
    m = re.fullmatch(r"(\d{4})-Q([1-4])", p)
    if m:
        mo, dd = _Q_END[int(m.group(2))]
        return date(int(m.group(1)), mo, dd)
    m = re.fullmatch(r"(\d{4})-(\d{2})", p)
    if m:
        y, mo = int(m.group(1)), int(m.group(2))
        if 1 <= mo <= 12:
            return date(y, mo, monthrange(y, mo)[1])
    return None


def period_start_date(period: Optional[str]) -> Optional[date]:
    """Date a period label STARTS on. A period is "future" iff its start > today
    (so the current, in-progress period is kept; only genuinely-future ones drop)."""
    if not period:
        return None
    p = period.strip().upper()
    m = re.fullmatch(r"(\d{4})", p)
    if m:
        return date(int(m.group(1)), 1, 1)
    m = re.fullmatch(r"(\d{4})-Q([1-4])", p)
    if m:
        mo, dd = _Q_START[int(m.group(2))]
        return date(int(m.group(1)), mo, dd)
    m = re.fullmatch(r"(\d{4})-(\d{2})", p)
    if m:
        y, mo = int(m.group(1)), int(m.group(2))
        if 1 <= mo <= 12:
            return date(y, mo, 1)
    return None


def _series_by_code(db: Session, include_future: bool = False) -> Dict[str, List[tuple]]:
    """Group observations into ``{series_code: [(period, value), ...]}`` sorted.

    Future periods (those that START after today) are dropped by default — some
    Excel sheets carry projected months that must not pollute the snapshot label,
    the "latest value" or momentum. The current in-progress period is kept. Set
    *include_future* to keep everything.
    """
    today = date.today()
    grouped: Dict[str, list] = defaultdict(list)
    for row in db.query(MacroSeries).all():
        if not include_future:
            start = period_start_date(row.period)
            if start is not None and start > today:
                continue
        grouped[row.series_code].append((row.period, row.value))
    for code in grouped:
        grouped[code].sort(key=lambda pv: (period_end_date(pv[0]) or date.min, pv[0]))
    return grouped


def build_snapshot(db: Session, period: Optional[str] = None) -> Dict[str, Any]:
    """Compute momentum + signals across all series, persist and publish.

    *period* labels the snapshot; defaults to the latest period observed.
    """
    grouped = _series_by_code(db)
    if not grouped:
        raise ValueError("No hay series macro ingeridas; corra ingest_series primero.")

    momentum = {code: compute_series_momentum(obs) for code, obs in grouped.items()}

    # Early-warning inputs.
    debt_obs = grouped.get(DEBT_SERIES, [])
    debt_latest = next((v for _, v in reversed(debt_obs) if v is not None), None)
    flow_pct = {
        code: momentum[code]["pct_change"]
        for code in grouped if code in FLOW_SERIES
    }
    signals = detect_signals(debt_latest, flow_pct)

    if period is None:
        # Latest CLOSED period (grouped already excludes future), chosen
        # chronologically — lexical max mis-ranks mixed formats ("2026-Q1" > "2026-06").
        all_periods = [p for obs in grouped.values() for p, _ in obs]
        if not all_periods:
            raise ValueError("Solo hay períodos futuros; no hay período cerrado para el snapshot.")
        period = max(all_periods, key=lambda p: (period_end_date(p) or date.min, p))

    snapshot = db.query(MacroSnapshot).filter_by(period=period).first()
    if snapshot is None:
        snapshot = MacroSnapshot(period=period)
        db.add(snapshot)
    snapshot.momentum = momentum
    snapshot.signals = signals
    snapshot.series_count = len(grouped)
    snapshot.signal_count = len(signals)
    snapshot.model_version = MODEL_VERSION

    db.commit()
    db.refresh(snapshot)

    # Macro→sectorial contract (Eje 3 consumes it). Function-level import: the
    # producer imports this module, so a top-level import would be circular.
    from modules.macro_monitor.macro_context import build_macro_context
    contract = build_macro_context(db, period=period, grouped=grouped)
    contract_dict = contract.to_dict()
    # Persist to a shared AppSetting so sector_intel can read the contract without
    # a cross-module import (it derives each sector's macro_exposure from it).
    _persist_macro_contract(db, contract_dict)
    # Persist the BCRD inflation series too, so pension_intel can deflate its nominal
    # returns into real terms without importing this module (the contract carries only
    # the latest value; deflating a trajectory needs the full history).
    _persist_inflation_series(db, grouped)

    payload = {
        "period": period,
        "series_count": len(grouped),
        "signal_count": len(signals),
        "signals": signals,
        "contract": contract_dict,
    }
    publish_macro_updated(payload)
    logger.info(
        "Snapshot macro %s: %d series, %d señales", period, len(grouped), len(signals)
    )
    return {
        "period": period,
        "snapshot_id": snapshot.id,
        "series_count": len(grouped),
        "momentum": momentum,
        "signals": signals,
        "model_version": MODEL_VERSION,
    }


def _persist_macro_contract(db: Session, contract: Dict[str, Any]) -> None:
    """Upsert the latest macro→sectorial contract into a shared AppSetting.

    Lets ``sector_intel`` read it (for each sector's macro_exposure) without
    importing this module — the contract type/key live in ``shared.contracts``.
    """
    import json

    from shared.contracts import APP_SETTING_KEY
    from shared.settings.models import AppSetting

    row = db.query(AppSetting).filter(AppSetting.key == APP_SETTING_KEY).first()
    payload = json.dumps(contract)
    if row is None:
        db.add(AppSetting(key=APP_SETTING_KEY, value=payload, is_secret=False))
    else:
        row.value = payload
    db.commit()


def _persist_inflation_series(db: Session, grouped: Dict[str, List[tuple]]) -> None:
    """Upsert the BCRD year-over-year inflation series into a shared AppSetting so
    pension_intel can deflate nominal returns without importing this module. No-op if
    the series is absent (never writes an empty payload)."""
    import json

    from shared.contracts import INFLATION_SERIES_CODE, INFLATION_SERIES_KEY
    from shared.settings.models import AppSetting

    obs = grouped.get(INFLATION_SERIES_CODE) or []
    series = [[p, v] for p, v in obs if v is not None]
    if not series:
        return
    row = db.query(AppSetting).filter(AppSetting.key == INFLATION_SERIES_KEY).first()
    payload = json.dumps(series)
    if row is None:
        db.add(AppSetting(key=INFLATION_SERIES_KEY, value=payload, is_secret=False))
    else:
        row.value = payload
    db.commit()


def get_indicators(db: Session) -> List[Dict[str, Any]]:
    """Latest momentum read per series (for the /indicators view)."""
    grouped = _series_by_code(db)
    out = []
    for code, obs in sorted(grouped.items()):
        m = compute_series_momentum(obs)
        # n_obs lets the UI default the trajectory chart to a series with depth
        # (snapshot-only series have 1-2 points and can't be plotted/projected).
        out.append({"series_code": code, "n_obs": len(obs), **series_label(code), **m})
    return out


def get_series(db: Session, series_code: str) -> Dict[str, Any]:
    """Return one series' observations (period-ordered) + its momentum read."""
    grouped = _series_by_code(db)
    obs = grouped.get(series_code, [])
    momentum = compute_series_momentum(obs) if obs else None
    return {
        "series_code": series_code,
        "observations": [{"period": p, "value": v} for p, v in obs],
        "momentum": momentum,
    }


def delete_series(db: Session, series_code: str) -> int:
    """Delete every observation of *series_code*.  Returns rows removed.

    Maintenance op for orphaned codes: ``ingest_series`` upserts by
    (series_code, period) and never prunes codes the parser stopped emitting, so
    a schema change (e.g. collapsing per-year codes into one annual series) can
    leave stale rows behind.  Idempotent — deleting an absent code returns 0.
    """
    deleted = (
        db.query(MacroSeries)
        .filter_by(series_code=series_code)
        .delete(synchronize_session=False)
    )
    db.commit()
    logger.info("Borrado de serie macro '%s': %d observaciones", series_code, deleted)
    return deleted


def get_snapshot(db: Session, period: Optional[str] = None) -> Optional[MacroSnapshot]:
    """Persisted snapshot for *period* (latest CLOSED one if omitted).

    Picks chronologically (lexical ``period desc`` mis-ranks mixed formats) and
    skips future-labeled snapshots — a stale future snapshot (e.g. left by a
    pre-fix build) must not resurface as "the latest".
    """
    q = db.query(MacroSnapshot)
    if period:
        return q.filter_by(period=period).first()
    today = date.today()
    snaps = q.all()
    if not snaps:
        return None
    closed = [s for s in snaps if (period_start_date(s.period) or date.min) <= today]
    pool = closed or snaps  # degenerate: only future snapshots exist → least-bad
    return max(pool, key=lambda s: (period_end_date(s.period) or date.min, s.period))
