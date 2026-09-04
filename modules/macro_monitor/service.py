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
from typing import Any, Dict, List, Optional, Set

from sqlalchemy.orm import Session

from shared.data.base_client import SourceClient
from shared.data.bcrd_client import bcrd_client, resolve_bcrd_client, series_label
from shared.data.series_cadence import cadencia_de_periodo, discrepancia_de_cadencia
from shared.data.series_nature import infer_nature
from shared.data.bcrd_excel.canonical import (
    curated_label as canonical_label,
    is_curated as canonical_is_curated,
    note_for as canonical_note_for,
)
from modules.macro_monitor.events import publish_macro_updated
from modules.macro_monitor.models.models import MacroSeries, MacroSnapshot
from modules.macro_monitor.scoring.momentum import compute_series_momentum
from modules.macro_monitor.scoring.signals import detect_signals

logger = logging.getLogger("sdq.macro_monitor.service")

MODEL_VERSION = "1.0"

# Serie usada por la señal de deuda (Reinhart-Rogoff).
DEBT_SERIES = "public_debt_gdp"

# El panel de flujos externos de la señal Calvo `sudden_stop` ya NO es un set de códigos
# cortos: vive como doctrina en `shared/doctrine/macro_sector.yaml` → `flow_panel`, con la
# serie canónica VIVA de cada flujo. Se lee vía :func:`_flow_pct_panel`.


#: Un código de serie desempatado por ÍNDICE DE COLUMNA: se llama «la segunda columna que
#: también se llamaba tasa de inflación», y eso no dice de QUÉ es.
#:
#: Es la ÚLTIMA red, no la primera. El desempate correcto lo hace `inference`, calificando
#: con el encabezado del grupo (`quintil_2 · tasa de inflación`); solo cuando ni el vecino
#: aporta un rótulo distinto queda la coordenada, y ahí la serie es genuinamente
#: innombrable. La primera reacción a las dieciocho series `_c<n>` de producción fue vetarlas
#: acá y ya: estaba mal, eran series bien medidas y mal nombradas —se verificó que cada tasa
#: del IPC por quintiles coincide con error 0,00000 pp con la variación mensual de su
#: índice—. Descartar un dato porque el nombre está roto es arreglar el síntoma tirando la
#: medición.
#:
#: Vale para las DOS coordenadas. Cubría solo la columna (`_c<n>`), y la de FILA (`_r<n>`)
#: pasaba: un cuadro que repite los mismos sectores en tres bloques —nivel, tasa de
#: crecimiento, incidencia— produce `agropecuario`, `agropecuario_r46` y `agropecuario_r83`,
#: y las dos últimas dicen en qué FILA estaban, no cuál de los tres miden. El PIB sectorial
#: por origen entra con ~196 series así. Al agregarse esta mitad no se vetó nada de lo
#: existente: había CERO códigos `_r<n>` en las 600 series del canónico.
_CODIGO_SIN_SUJETO = re.compile(r"_[cr]\d+$")


def _sin_sujeto(codigo: str) -> bool:
    """¿El código de la serie perdió su sujeto al desempatarse por coordenada?"""
    return bool(_CODIGO_SIN_SUJETO.search(codigo or ""))


def _upsert_records(db: Session, records) -> int:
    """Upsert a list of :class:`Record` into MacroSeries (by series_code+period).

    Dedupes the batch by (series_code, period) first: the Excel extractor can emit
    duplicate rows for some flagged layouts, and the session is ``autoflush=False``,
    so two same-key rows both pass the per-row "not found" check and then collide at
    commit (Postgres UniqueViolation on uq_mm_series_period). Last-wins matches the
    per-row upsert semantics.
    """
    # Dedupe por (serie, período). "Último gana" SALVO que el último sea nulo: un valor
    # real jamás debe ser pisado por un vacío del mismo lote. Pasa cuando la planilla trae
    # columnas de relleno a la derecha del último año: el extractor emite el valor real y
    # luego dos celdas vacías para el mismo período, y el último-gana ingenuo dejaba el
    # período en None — borrando dato publicado. No fabricar y no destruir son la misma
    # disciplina.
    # NO SE PERSISTE lo que no nombra su sujeto. Se descarta acá —en la frontera de
    # escritura— y no en cada extractor, porque es la única puerta por la que pasan todos.
    # Y se REGISTRA lo descartado: un veto silencioso se lee como que la planilla no traía
    # esas columnas.
    descartadas = sorted({r.series for r in records if _sin_sujeto(r.series)})
    if descartadas:
        logger.info("macro: %d serie(s) NO se persisten porque su código se desempató por "
                    "coordenada de columna y no dice de qué son: %s",
                    len(descartadas), ", ".join(descartadas[:8]))
        records = [r for r in records if not _sin_sujeto(r.series)]

    deduped: Dict[tuple, Any] = {}
    for r in records:
        key = (r.series, r.period)
        prev = deduped.get(key)
        if prev is not None and r.value is None and prev.value is not None:
            continue
        deduped[key] = r
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
        # La naturaleza se resuelve EN LA INGESTA, con la unidad que el emisor declaró y el
        # código de la serie a la vista. Hacerlo al leer obligaría a cada consumidor a
        # repetir la inferencia — y a equivocarse cada uno a su manera.
        nat = infer_nature(unit=r.unit, code=r.series)
        # La CADENCIA también se resuelve en la ingesta, por el mismo motivo que la
        # naturaleza: dejarla nula obligaba a cada lector a derivarla, y el que la sirve por
        # la Data API lo hacía sobre el conjunto de períodos de la serie —devolviendo
        # "unknown" en cuanto uno solo tuviera otro formato—. Acá se resuelve por FILA, que
        # es donde la etiqueta del período es inequívoca.
        cad = cadencia_de_periodo(str(r.period))
        if row is None:
            db.add(MacroSeries(
                series_code=r.series, period=r.period, value=r.value,
                unit=r.unit, source=src, published_at=pub, license=lic, nature=nat,
                frequency=cad,
            ))
        else:
            # "Un valor real jamás lo pisa un vacío" vale también ENTRE corridas, no solo
            # dentro del lote. Esta rama hacía la asignación incondicional: un lote posterior
            # con una celda que el BCRD todavía no publicó —o un parse fallido— BORRABA el
            # valor ya persistido, en silencio. Mientras `mm_series` no tuvo el corpus Excel
            # el defecto no podía destruir nada porque no había qué pisar; encender la
            # persistencia es lo que lo vuelve vivo, porque desde la segunda corrida toda
            # observación entra por acá. El guard frena el nulo y nada más: un valor real
            # posterior sigue actualizando, que es como entra una revisión del emisor.
            if r.value is not None:
                row.value = r.value
            row.frequency = cad
            row.unit = r.unit
            row.source = src
            row.published_at = pub
            row.license = lic
            row.nature = nat
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
    # E2E-MM2: frescura del balance fiscal. El Estado de Operaciones de Hacienda se publica
    # con rezago (a jul-2026 su último cierre es 2025-12) mientras la recaudación DGII llega
    # mucho más al día. Se expone la asimetría para que la narrativa NO presente un déficit
    # de hace meses como "el cierre" sin advertir su antigüedad (rezago de FUENTE, no de sync).
    def _months_between(p_old, p_new):
        try:
            yo, mo = (int(x) for x in p_old.split("-")[:2])
            yn, mn = (int(x) for x in p_new.split("-")[:2])
            return (yn - yo) * 12 + (mn - mo)
        except Exception:  # noqa: BLE001
            return None

    eo_behind = _months_between(latest, dgii_latest)
    eo_lag_note = None
    if eo_behind and eo_behind >= 2:
        eo_lag_note = (
            f"El balance fiscal (Hacienda · Estado de Operaciones) más reciente publicado "
            f"corresponde a {latest}; la recaudación (DGII) llega hasta {dgii_latest}. "
            f"El déficit se lee con ese rezago de fuente ({eo_behind} meses)."
        )
    return {
        "has_data": True,
        "period_range": [all_periods[0], all_periods[-1]],
        "latest_period": latest,
        "eo_unit": "RD$ millones",
        "eo": eo,
        "eo_latest": eo_latest,
        "recaudacion_unit": "RD$",
        "recaudacion": {"period": dgii_latest, "groups": recaudacion},
        "freshness": {"eo_asof": latest, "dgii_asof": dgii_latest,
                      "eo_months_behind_dgii": eo_behind, "eo_lag_note": eo_lag_note},
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


def _flags_del_reporte(report) -> List[Dict[str, Any]]:
    """Las marcas que se guardan por archivo. El aviso de ARCHIVO va PRIMERO y sin recorte.

    Los avisos de archivo —hoy, que el rango del spec dejó afuera períodos que el encabezado
    declara— no pertenecen a ninguna serie, así que no vienen en `flagged`. Si se anexaran al
    final, el corte `[:20]` los tiraría justo en los archivos con muchas series marcadas, que
    son los que más falta hace mirar.
    """
    avisos = list(getattr(report, "avisos", []) or [])
    cabeza = [{"code": "__archivo__", "flags": avisos}] if avisos else []
    return cabeza + [{"code": s.code, "flags": s.flags} for s in report.flagged][:20]


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
                    "flags": _flags_del_reporte(r.report),
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


def _discrepancias_de_cadencia(entradas, records) -> List[str]:
    """Dónde la cadencia DECLARADA por el registro contradice a la de los períodos.

    El puente entre una entrada canónica (clave ``pib_real``) y las series persistidas
    (``bcrd.xls.pib_2018.serie_original_indice``) es ``excel_series_suffix``; una entrada sin
    él no tiene a qué serie apuntar y no se puede verificar — son 17 de 50, y eso es un hecho
    declarado, no un olvido. Ver §4 del spec de persistencia.
    """
    periodos_por_serie: Dict[str, List[str]] = defaultdict(list)
    for rec in records:
        periodos_por_serie[str(rec.series)].append(str(rec.period))

    out: List[str] = []
    for s in entradas:
        if not s.excel_series_suffix:
            continue
        for code, periodos in periodos_por_serie.items():
            if not code.endswith(s.excel_series_suffix):
                continue
            detalle = discrepancia_de_cadencia(s.frequency, periodos)
            if detalle:
                out.append(f"{s.key} · {code}: {detalle}")
    return out


def _registros_de_las_hojas(archivo: str, hojas: List[str], records) -> List[Any]:
    """Los registros que salieron de *hojas*, por el prefijo que el motor le pone al código.

    Un libro multi-hoja produce ``bcrd.xls.<archivo>.<hoja>.<métrica>``; el segmento de hoja
    lo arma el motor con su propio ``_slug``, así que acá se usa ESE, no una transformación
    escrita a mano — reconstruir un identificador derivado a ojo es cómo se llega a un filtro
    que no encuentra nada y se lee como que la hoja venía vacía.

    **El punto final del prefijo no es cosmético:** `pib_trim` es prefijo de `pib_trim_acum`,
    y sin él habilitar la hoja limpia arrastraría la rota, que es justo lo que este alcance
    existe para impedir.

    Lanza si las hojas declaradas no producen nada: puede ser un nombre mal escrito o un libro
    de UNA sola hoja —ahí el motor no pone segmento de hoja y el prefijo no matchea nunca—, y
    escribir cero en silencio se lee, meses después, como que la fuente dejó de traer datos.
    """
    from shared.data.bcrd_excel.extract import _slug, default_prefix

    base = default_prefix(archivo)
    prefijos = tuple(f"{base}.{_slug(h)}." for h in hojas)
    elegidos = [x for x in records if str(x.series).startswith(prefijos)]
    if not elegidos:
        raise ValueError(
            f"El alcance de {archivo} declara la(s) hoja(s) {hojas} y ninguna serie extraída "
            f"empieza con {list(prefijos)}. O el nombre de la hoja no es ése, o el libro tiene "
            f"una sola hoja (ahí el código no lleva segmento de hoja y el alcance por hoja no "
            f"aplica)."
        )
    return elegidos


def _con_unidades_curadas(records: List[Any]) -> List[Any]:
    """Aplica las unidades verificadas del registro canónico antes de escribir.

    Va acá —en la ingesta canónica, no en el extractor— porque es un hecho CURADO por un
    analista sobre un archivo concreto, con su verificación escrita, y no una regla que el
    motor pueda derivar de la planilla. Ver `canonical.UNIDADES_CURADAS`.
    """
    from dataclasses import replace

    from shared.data.bcrd_excel import canonical

    salida = []
    for r in records:
        curada = canonical.unidad_curada(r.series)
        salida.append(replace(r, unit=curada) if curada and curada != r.unit else r)
    return salida


def ingest_canonical(db: Session, *, persist: bool = False,
                     alcance: Optional[Dict[str, Optional[List[str]]]] = None) -> Dict[str, Any]:
    """Run the engine over ONLY the canonical source files (not the whole catalog).

    Dedupes shared source files (e.g. reserves brutas/netas come from one file).
    Upserts a per-file report; with *persist*, upserts the extracted series too.

    *alcance* acota QUÉ SE ESCRIBE, no qué se lee: se recorren y se reportan los 26 archivos
    igual —el reporte de cobertura es el instrumento con el que se decide qué habilitar
    después, y perderlo sería quedarse ciego justo donde falta mirar— pero solo se persiste lo
    que esté en el mapa. `None` = todo, el comportamiento histórico.

    Es un mapa ``{archivo: None | [hojas]}``: `None` habilita el archivo entero y una lista
    habilita SOLO esas hojas, para los libros en que unas extraen bien y otras no. Ver
    `canonical.PERSISTIBLES_VERIFICADOS`, que además declara por qué está afuera cada uno.
    """
    from shared.data.bcrd_excel import canonical
    from shared.data.bcrd_excel.catalog import find_entry
    from shared.data.bcrd_excel.engine import SpecCache, ingest_excel

    habilitados = dict(alcance) if alcance else None
    cache = SpecCache()
    seen: set = set()
    ok = flagged = failed = 0
    persistidos_total = 0
    omitidos: List[str] = []
    discrepancias: List[str] = []
    por_hoja: List[str] = []
    # Un archivo puede declarar VARIAS series canónicas (el IPC general y la inflación
    # interanual salen del mismo). La cadencia se verifica contra cada declaración, no
    # contra la primera que aparezca.
    por_archivo: Dict[str, List[Any]] = defaultdict(list)
    for s in canonical.registry():
        por_archivo[s.source_file].append(s)
    for s in canonical.registry():
        if s.source_file in seen:
            continue
        seen.add(s.source_file)
        entry = find_entry(s.source_file)
        if entry is None:
            failed += 1
            continue
        escribir = persist and (habilitados is None or s.source_file in habilitados)
        hojas = habilitados.get(s.source_file) if (habilitados and escribir) else None
        if persist and not escribir:
            omitidos.append(s.source_file)
        try:
            r = ingest_excel(entry, cache=cache, use_claude=True)
            status = "ok" if r.report.ok else "flagged"
            escribibles = _con_unidades_curadas(
                _registros_de_las_hojas(s.source_file, hojas, r.records)
                if hojas else r.records)
            persisted = _upsert_records(db, escribibles) if escribir else 0
            if hojas:
                por_hoja.append(f"{s.source_file}: {len(hojas)} hoja(s), "
                                f"{len(escribibles)} de {len(r.records)} registros")
            # La cadencia que el registro DECLARA contra la que dicen los períodos. No se
            # usa para elegir el valor —eso lo resuelve la etiqueta del período, que es
            # dato— sino para detectar un eje temporal mal leído: una serie declarada
            # trimestral cuyos períodos salen mensuales tiene el parse roto, y la serie
            # entera es sospechosa. Se DECLARA en vez de resolverse en silencio.
            #
            # Va DESPUÉS del upsert y no puede lanzar: es un diagnóstico, y un diagnóstico
            # que rompe lo que diagnostica es peor que no tenerlo. Escrito primero antes y
            # sin proteger, un registro con otra forma tumbaba el archivo ENTERO —los 26
            # pasaban a `failed` y no se persistía nada—. Lo cazó
            # `test_ingest_canonical_continues_after_a_failing_file`.
            try:
                discrepancias.extend(
                    _discrepancias_de_cadencia(por_archivo[s.source_file], r.records))
            except Exception:  # noqa: BLE001 — el diagnóstico jamás rompe la ingesta
                logger.debug("no se pudo verificar la cadencia de %s", entry.filename,
                             exc_info=True)
            persistidos_total += persisted
            _upsert_excel_report(db, {
                "file_url": entry.url, "filename": entry.filename, "sector": entry.sector,
                "status": status, "method": r.spec.method, "orientation": r.spec.orientation,
                "frequency": r.spec.frequency, "confidence": r.spec.confidence,
                "n_records": len(r.records), "n_series": len(r.report.series),
                "n_flagged": len(r.report.flagged), "persisted": persisted, "error": None,
                "flags": _flags_del_reporte(r.report),
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
    if omitidos:
        # Lo acotado se DECLARA. Un alcance que recorta en silencio se lee, tres meses
        # después, como que esos archivos no traían nada.
        logger.info("[macro] ingesta canónica: %d archivo(s) leídos y reportados pero NO "
                    "persistidos por alcance (%s): %s", len(omitidos),
                    "canonical.PERSISTIBLES_VERIFICADOS", ", ".join(sorted(omitidos)))
    if discrepancias:
        logger.warning("[macro] ingesta canónica: %d serie(s) con la cadencia DECLARADA en "
                       "contra de sus períodos — el eje temporal se leyó mal: %s",
                       len(discrepancias), "; ".join(discrepancias[:8]))
    if por_hoja:
        logger.info("[macro] ingesta canónica: alcance por HOJA en %d archivo(s): %s",
                    len(por_hoja), "; ".join(por_hoja))
    return {"files": len(seen), "ok": ok, "flagged": flagged, "failed": failed,
            "persisted": persistidos_total,
            "persist_scope": (dict(sorted(habilitados.items())) if habilitados else "todos"),
            "sheet_scope": por_hoja,
            "skipped_by_scope": sorted(omitidos),
            "cadence_mismatches": discrepancias}


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

    Handles ``YYYY``, ``YYYY-MM``, ``YYYY-Qn`` (case-insensitive) and ``YYYY-MM-DD``.
    Returns None when unparseable, so callers can decide how to treat it.

    El DÍA se resuelve PRIMERO: `2026-03-07` también empieza con algo que parece `YYYY-MM`,
    y sin este orden un día se ordenaría como si fuera el mes entero.
    """
    if not period:
        return None
    p = period.strip().upper()
    m = re.fullmatch(r"(\d{4})-(\d{2})-(\d{2})", p)
    if m:
        try:
            return date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
        except ValueError:
            return None
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
    (so the current, in-progress period is kept; only genuinely-future ones drop).

    Un día empieza y termina el mismo día; el orden de las ramas importa por lo mismo que en
    :func:`period_end_date`."""
    if not period:
        return None
    p = period.strip().upper()
    m = re.fullmatch(r"(\d{4})-(\d{2})-(\d{2})", p)
    if m:
        try:
            return date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
        except ValueError:
            return None
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


def _effective_nature(code: str, unit: Optional[str], persisted: Optional[str]) -> str:
    """Naturaleza de una serie, resuelta de UNA sola autoridad, en orden de fuerza:

    1. **Declaración propia.** Los códigos que emiten nuestros conectores tipados
       (``remittances``, ``public_debt_gdp``, ``reserves``…) tienen naturaleza
       DETERMINÍSTICA: la definimos nosotros. No dependen de que un ingestor la escriba.
    2. **Columna persistida.** Para las series de planilla la resolvió la ingesta con la
       unidad que declaró el emisor; se lee tal cual.
    3. **Unidad de la fila.** Muchos conectores (fiscal, inflación, IPC) NO pasan por la
       ingesta de Excel y nunca escribieron la columna — pero SÍ persistieron la unidad.
       Inferir de esa unidad da EXACTAMENTE el mismo resultado que la ingesta habría dado
       (la unidad no cambia), así que no es adivinar: es cerrar el hueco de que la
       resolución estuviera partida entre conectores. Sin unidad, ``unknown`` honesto.
    """
    from shared.data.series_nature import DECLARED, infer_nature

    leaf = code.split(".")[-1].lower()
    if leaf in DECLARED or code.lower() in DECLARED:
        return infer_nature(code=code)
    if persisted:
        return persisted
    return infer_nature(unit=unit, code=code)


def _nature_by_code(db: Session) -> Dict[str, str]:
    """``{series_code: nature}`` para el cómputo, vía :func:`_effective_nature`."""
    rows: Dict[str, tuple] = {}
    for code, nat, unit in db.query(
            MacroSeries.series_code, MacroSeries.nature, MacroSeries.unit).distinct():
        code = str(code)
        # Primera fila con columna/unidad no nula gana; da igual el orden para el resultado.
        cur = rows.get(code)
        rows[code] = (nat or (cur[0] if cur else None), unit or (cur[1] if cur else None))
    return {code: _effective_nature(code, unit, nat) for code, (nat, unit) in rows.items()}


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


def _flow_pct_panel(
    grouped: Dict[str, List[tuple]],
) -> tuple[Dict[str, float], Dict[str, Dict[str, str]]]:
    """Contracción INTERANUAL (YoY) de cada flujo externo del panel de `sudden_stop`.

    Lee ``flow_panel`` de la doctrina (``macro_sector.yaml``), y por cada flujo mide el YoY
    de su serie canónica viva con :func:`macro_context._yoy_change` — agnóstica de cadencia
    (anual o mensual) y sign-correcta por construir el cambio como cociente. Un flujo cuya
    serie no exista, no tenga ancla YoY o cruce el cero se OMITE y se registra: la ausencia
    es un resultado honesto, no un hueco que se rellena.

    Devuelve ``({key: yoy_pct}, {key: {series_code, label}})`` — el mapa de metadatos deja
    que la señal cite el nombre semántico y la serie canónica sin re-consultar la doctrina.
    """
    from shared.doctrine import load_doctrine_raw
    # Import a nivel de función: macro_context importa este módulo (ciclo si fuera al tope).
    from modules.macro_monitor.macro_context import _yoy_change

    panel = load_doctrine_raw("macro_sector").get("flow_panel") or []
    flow_pct: Dict[str, float] = {}
    flow_meta: Dict[str, Dict[str, str]] = {}
    for entry in panel:
        key = entry.get("key")
        code = entry.get("series_code")
        if not key or not code:
            continue
        clean = [(p, float(v)) for p, v in grouped.get(code, []) if v is not None]
        yoy = _yoy_change(clean) if len(clean) >= 2 else None
        if yoy is None:
            logger.info(
                "sudden_stop: flujo '%s' omitido — serie '%s' sin YoY computable "
                "(sin ancla a ~1 año, base cero, cruce de cero o serie ausente)", key, code)
            continue
        flow_pct[key] = yoy
        flow_meta[key] = {"series_code": code, "label": entry.get("label") or key}
    return flow_pct, flow_meta


def build_snapshot(db: Session, period: Optional[str] = None) -> Dict[str, Any]:
    """Compute momentum + signals across all series, persist and publish.

    *period* labels the snapshot; defaults to the latest period observed.
    """
    grouped = _series_by_code(db)
    if not grouped:
        raise ValueError("No hay series macro ingeridas; corra ingest_series primero.")

    # Cada serie se lee según SU naturaleza declarada, no con una transformación única.
    natures = _nature_by_code(db)
    momentum = {code: compute_series_momentum(obs, nature=natures.get(code, "unknown"))
                for code, obs in grouped.items()}

    # Early-warning inputs.
    debt_obs = grouped.get(DEBT_SERIES, [])
    debt_latest = next((v for _, v in reversed(debt_obs) if v is not None), None)
    # Panel de flujos externos: YoY canónico y sign-correcto, no el `pct_change`
    # período-a-período del momentum (que en series mensuales sería ruido estacional y en
    # las de signo negativo del MBP6 leería el signo al revés).
    flow_pct, flow_meta = _flow_pct_panel(grouped)
    signals = detect_signals(debt_latest, flow_pct, flow_meta=flow_meta)

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
    # Persist the BCRD policy rate (TPM) series too, so pension_intel can use it as the
    # risk-free rate for the Sharpe ratio (ISA riesgo narrative) without importing macro.
    _persist_tpm_series(db, grouped)

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


def _persist_tpm_series(db: Session, grouped: Dict[str, List[tuple]]) -> None:
    """Upsert the BCRD policy rate (TPM) series into a shared AppSetting so pension_intel
    can use it as the risk-free rate (Sharpe) without importing this module. No-op if the
    series is absent (never writes an empty payload)."""
    import json

    from shared.contracts import TPM_SERIES_CODE, TPM_SERIES_KEY
    from shared.settings.models import AppSetting

    obs = grouped.get(TPM_SERIES_CODE) or []
    series = [[p, v] for p, v in obs if v is not None]
    if not series:
        return
    row = db.query(AppSetting).filter(AppSetting.key == TPM_SERIES_KEY).first()
    payload = json.dumps(series)
    if row is None:
        db.add(AppSetting(key=TPM_SERIES_KEY, value=payload, is_secret=False))
    else:
        row.value = payload
    db.commit()


def get_indicators(db: Session) -> List[Dict[str, Any]]:
    """Latest momentum read per series (for the /indicators view)."""
    grouped = _series_by_code(db)
    natures = _nature_by_code(db)   # cada serie se lee según SU naturaleza declarada
    out = []
    for code, obs in sorted(grouped.items()):
        m = compute_series_momentum(obs, nature=natures.get(code, "unknown"))
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


#: Qué proporción de lo que produce el motor tiene que estar ya en el destino para que la
#: poda sea segura. No es un umbral de calidad: es la comprobación de que el PASO 2 —la
#: sincronización con el código corregido— ya ocurrió. Por debajo, lo que hay en el destino
#: lo escribió otra versión y borrar dejaría un hueco que nadie repone hasta el mes
#: siguiente. La mitad es holgado a propósito: no hace falta afinarlo para distinguir «ya
#: corrió» de «no corrió», y un umbral exacto se rompería con el primer archivo nuevo.
_MINIMO_DE_LO_NUEVO_YA_PRESENTE = 0.5


def huerfanas_podables(en_destino: Set[str], produce_el_motor: Set[str],
                       antes_de_sincronizar: Set[str], prefijo: str = "bcrd.xls.") -> Set[str]:
    """Qué códigos del destino se pueden podar, y por qué solo esos.

    Huérfano es un código que el motor ya no produce. Pero «lo que el motor produce» no se
    puede leer desde acá y creerle: el nombrado de las filas ambiguas lo resuelve el MODELO,
    y en producción puede rotular la misma fila distinto que en el entorno donde se corre
    esta poda. Medido el 2026-09-04: 53 códigos —del PIB por origen, las llegadas y la
    balanza de pagos— salieron con nombres distintos en los dos entornos. Compararlos contra
    el motor local y nada más los marcaba como huérfanos, y son series recién escritas.

    La regla que lo cierra es observable y no depende del modelo: **un código que no estaba
    en el destino ANTES de la sincronización, lo escribió la sincronización**. Por eso la
    poda se restringe a lo que ya estaba.

    Queda un residuo declarado: un código viejo que la sincronización SÍ reescribió pero que
    el motor local nombra distinto se podaría de más. Vuelve en la sincronización siguiente
    —la poda no borra la fuente, solo la copia—, y por eso el protocolo es podar, volver a
    sincronizar y comprobar qué reapareció.
    """
    return {s for s in en_destino
            if s.startswith(prefijo)
            and s not in produce_el_motor
            and s in antes_de_sincronizar}


def por_que_no_podar(vivos: Set[str], en_destino: Set[str]) -> str:
    """Motivo por el que NO se debe podar ahora, o cadena vacía si se puede.

    La poda solo es correcta DESPUÉS de que el destino haya recibido los códigos nuevos. Si
    se corre antes, borra observaciones que se están sirviendo y no vuelve nada — y con el
    código viejo desplegado, la siguiente sincronización las repone con el nombre y el valor
    equivocados. Este es el paso que impide ese error de ORDEN.
    """
    if not vivos:
        return "el motor no produjo ninguna serie: no hay contra qué comparar"
    presentes = len(vivos & en_destino)
    if presentes < len(vivos) * _MINIMO_DE_LO_NUEVO_YA_PRESENTE:
        return (f"de las {len(vivos)} series que produce el motor, el destino solo tiene "
                f"{presentes} ({presentes / len(vivos):.0%}). El código corregido no está "
                f"desplegado o `macro-canonical-sync` no corrió todavía. Borrar ahora "
                f"dejaría un hueco.")
    return ""


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


# ─── Superficie para la Data API (docs/SPEC_API_DATOS_PROPIETARIOS.md) ──
#
# El módulo describe y lee sus propias series; la capa API nunca consulta MacroSeries
# directamente (`shared/*` no importa módulos de sector). Agregar una serie al ingestor
# la publica sola: estas dos funciones la descubren sin que nadie las edite.


def _series_license(rows: List[MacroSeries]) -> Optional[str]:
    """Licencia de una serie, FAIL-CLOSED.

    Devuelve la licencia solo si TODAS las observaciones la declaran y coinciden. Si
    falta en alguna fila, o hay dos licencias distintas mezcladas, devuelve ``None`` —
    y el manifiesto pone la serie en cuarentena. Es deliberado: no se redistribuye lo
    que no consta que se pueda redistribuir, y una serie con linaje mezclado es
    justamente el caso donde el error sería caro.
    """
    licenses = {(r.license or "").strip() for r in rows}
    if len(licenses) != 1:
        return None
    only = licenses.pop()
    return only or None


def _infer_frequency(periods: List[str]) -> str:
    """Cadencia DERIVADA del formato del período canónico ("2025" · "2025-Q1" · "2025-01").

    ``MacroSeries.frequency`` existe pero el ingestor no la puebla (los ``Record`` de los
    conectores no la traen), así que leerla directo devolvería "unknown" para TODAS las
    series y dejaría al consumidor sin saber si un dato es mensual o anual. El formato del
    período sí es dato real —lo fija el parser al normalizar—, así que se deriva de ahí.
    Si la serie mezcla formatos, no se elige uno: "unknown" es la respuesta honesta.
    """
    kinds = set()
    for p in periods:
        p = (p or "").strip()
        if re.fullmatch(r"\d{4}-\d{2}-\d{2}", p):
            kinds.add("daily")
        elif re.fullmatch(r"\d{4}", p):
            kinds.add("annual")
        elif re.fullmatch(r"\d{4}-Q[1-4]", p, re.IGNORECASE):
            kinds.add("quarterly")
        elif re.fullmatch(r"\d{4}-\d{2}", p):
            kinds.add("monthly")
        else:
            kinds.add("unknown")
    return kinds.pop() if len(kinds) == 1 else "unknown"


def canonical_series_for_api(db: Session) -> List[Dict[str, Any]]:
    """Descriptores de todas las series canónicas normalizadas del monitor macro."""
    # ``str(...)`` en la frontera: ``MacroSeries`` usa el estilo legacy de SQLAlchemy,
    # cuyo tipo estático es ``Column[str]`` y no ``str``.
    rows_by_code: Dict[str, List[MacroSeries]] = defaultdict(list)
    for row in db.query(MacroSeries).all():
        rows_by_code[str(row.series_code)].append(row)

    out: List[Dict[str, Any]] = []
    for code, rows in sorted(rows_by_code.items()):
        rows.sort(key=lambda r: (period_end_date(str(r.period)) or date.min, str(r.period)))
        labels = series_label(code)
        units = [r.unit for r in rows if r.unit]
        declared = {str(r.frequency) for r in rows if getattr(r, "frequency", None)}
        sources = {str(r.source) for r in rows if r.source}
        out.append({
            "code": code,
            # La etiqueta curada MANDA sobre la humanización automática: "Balance fiscal
            # global del Gobierno Central" en vez de "Fiscal eo · balance global".
            "label": canonical_label(code) or labels.get("label") or code,
            "curated": canonical_is_curated(code),
            # Nota metodológica declarada (p.ej. qué manual de balanza de pagos rige la
            # serie y con cuál NO se encadena). Viaja al cliente por la Data API.
            "note": canonical_note_for(code),
            # Naturaleza estadística y en qué unidad se expresa su variación: sin esto un
            # consumidor no sabe si "+1.12" son puntos porcentuales o un 1.12%. Resuelta por
            # la MISMA autoridad que usa el cómputo, para que API y snapshot no discrepen.
            "nature": _effective_nature(
                code,
                next((str(r.unit) for r in rows if r.unit), None),
                next((str(r.nature) for r in rows if r.nature), None)),
            "unit": units[-1] if units else labels.get("unit"),
            # Se prefiere la cadencia DECLARADA; si el ingestor no la pobló (caso
            # general hoy), se deriva del formato del período.
            "frequency": (declared.pop() if len(declared) == 1
                          else _infer_frequency([str(r.period) for r in rows])),
            "source": ", ".join(sorted(sources)),
            "license": _series_license(rows),
            "period_first": rows[0].period if rows else None,
            "period_latest": rows[-1].period if rows else None,
            "n_obs": len(rows),
        })
    return out


def series_observations_for_api(
    db: Session,
    code: str,
    *,
    start: Optional[str] = None,
    end: Optional[str] = None,
    as_of: Optional[str] = None,
    limit: Optional[int] = None,
) -> List[Dict[str, Any]]:
    """Observaciones de una serie, ordenadas y con linaje.

    ``as_of`` es point-in-time REAL: filtra por la fecha de publicación del emisor. Si
    la serie no tiene ``published_at`` en su linaje, se levanta ``ValueError`` en vez de
    devolver la serie completa — servir el dato de hoy rotulado "as-of 2024" sería una
    mentira point-in-time, que es exactamente lo que el corte as-of existe para evitar.
    """
    rows = db.query(MacroSeries).filter_by(series_code=code).all()
    if not rows:
        return []
    rows.sort(key=lambda r: (period_end_date(str(r.period)) or date.min, str(r.period)))

    if as_of:
        if not any(r.published_at for r in rows):
            raise ValueError(
                f"La serie '{code}' no tiene fecha de publicación en su linaje: no se "
                f"puede honrar un corte point-in-time (as_of)."
            )
        cutoff = _parse_iso_date(as_of)
        if cutoff is None:
            raise ValueError(f"Fecha as_of inválida: '{as_of}'. Use formato ISO (AAAA-MM-DD).")
        rows = [r for r in rows if r.published_at and r.published_at <= cutoff]

    if start:
        floor = period_end_date(start) or date.min
        rows = [r for r in rows if (period_end_date(str(r.period)) or date.min) >= floor]
    if end:
        ceil = period_end_date(end) or date.max
        rows = [r for r in rows if (period_end_date(str(r.period)) or date.max) <= ceil]
    if limit is not None and limit > 0:
        rows = rows[-int(limit):]   # los más RECIENTES, que es lo que se pide por defecto

    return [
        {
            "period": r.period,
            "value": r.value,
            "unit": r.unit,
            "source": r.source,
            "published_at": r.published_at.isoformat() if r.published_at else None,
            "reason": None if r.value is not None else "sin dato publicado por la fuente",
        }
        for r in rows
    ]


def _parse_iso_date(value: str) -> Optional[date]:
    try:
        return date.fromisoformat(value.strip()[:10])
    except (ValueError, AttributeError):
        return None


def signals_for_api(db: Session, *, limit: Optional[int] = None) -> List[Dict[str, Any]]:
    """Señales de alerta temprana del último snapshot cerrado, para la Data API.

    Es la salida del motor determinista (``scoring/signals.detect_signals``) tal como se
    persistió — sin narrativa. Lista vacía = sin señal activa, que es un resultado, no
    un hueco."""
    snap = get_snapshot(db)
    if snap is None:
        return []
    persisted: List[Any] = list(snap.signals or [])
    out: List[Dict[str, Any]] = []
    for s in persisted:
        if not isinstance(s, dict):
            continue
        out.append({
            "key": str(s.get("signal") or s.get("key") or "signal"),
            "label": str(s.get("label") or s.get("signal") or "señal"),
            "severity": str(s.get("severity") or "info"),
            "period": str(snap.period),
            "subject": s.get("series") or s.get("subject"),
            "detail": str(s.get("detail") or s.get("framework") or ""),
        })
    if limit is not None and limit > 0:
        out = out[: int(limit)]
    return out
