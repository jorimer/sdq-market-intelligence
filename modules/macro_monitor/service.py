"""Macro Monitor — ingestion, snapshot computation, persistence & events.

Pipeline:
    1. ingest_series: pull records from a shared/data source → upsert MacroSeries.
    2. build_snapshot: compute per-series momentum + early-warning signals,
       persist a MacroSnapshot and publish ``macro.updated``.

The scoring (`scoring/momentum.py`, `scoring/signals.py`) is pure; this layer
wires it to the DB, the data layer and the event bus.
"""
import logging
from collections import defaultdict
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
    """Upsert a list of :class:`Record` into MacroSeries (by series_code+period)."""
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
        done_urls = {r.file_url for r in db.query(ExcelFileReport.file_url).all()}

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


def _series_by_code(db: Session) -> Dict[str, List[tuple]]:
    """Group all observations into ``{series_code: [(period, value), ...]}`` sorted."""
    grouped: Dict[str, list] = defaultdict(list)
    for row in db.query(MacroSeries).all():
        grouped[row.series_code].append((row.period, row.value))
    for code in grouped:
        grouped[code].sort(key=lambda pv: pv[0])
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
        period = max(p for obs in grouped.values() for p, _ in obs)

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

    payload = {
        "period": period,
        "series_count": len(grouped),
        "signal_count": len(signals),
        "signals": signals,
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
    """Persisted snapshot for *period* (latest if omitted)."""
    q = db.query(MacroSnapshot)
    if period:
        return q.filter_by(period=period).first()
    return q.order_by(MacroSnapshot.period.desc()).first()
