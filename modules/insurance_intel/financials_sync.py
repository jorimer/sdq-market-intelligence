"""SIS audited-financials ingest → per-insurer series + ISF.

Discovers the latest ``Estados-Financieros-Auditados-por-cia-<year>.xlsx`` on the SIS
transparencia page, downloads it, extracts every insurer's balance-sheet + income
figures (deterministic reconciled parse, ``external/audited_excel_extractor``), seeds
the insurer roster, persists per-entity series, and recomputes the ISF. Idempotent;
best-effort per sheet. Runs from Railway (static egress + browser UA).
"""
import logging
import re
from datetime import date
from typing import Callable, Dict, List, Optional

from sqlalchemy.orm import Session

from shared.data.lineage import Lineage
from modules.insurance_intel.external.audited_excel_extractor import (
    InsurerFinancials,
    extract_audited_workbook,
)
from modules.insurance_intel.models.models import InsuranceEntity, InsuranceSeries

logger = logging.getLogger("sdq.insurance_intel.financials_sync")

_AUDITED_PAGE = "https://sis.gob.do/transparencia/estados-financieros-auditados/"
_UA = "Mozilla/5.0 (SDQMIP research; +https://sdqconsulting.com.do)"
_SOURCE = "SIS"
_LICENSE = "https://opendatacommons.org/licenses/odbl/"


def discover_audited_urls() -> Dict[str, str]:
    """Scrape the transparencia page → ``{year: file_url}`` for the audited workbooks."""
    import requests

    r = requests.get(_AUDITED_PAGE, headers={"User-Agent": _UA}, timeout=45)
    r.raise_for_status()
    out: Dict[str, str] = {}
    for m in re.finditer(r'href="(https?://[^"]*Estados-Financieros-Auditados-por-cia-(\d{4})\.(xlsx|xls))"',
                         r.text, flags=re.I):
        url, year, _ext = m.group(1), m.group(2), m.group(3)
        # Prefer .xlsx when both exist for a year.
        if year not in out or url.lower().endswith(".xlsx"):
            out[year] = url
    return out


def _seed_entities(db: Session, fins) -> int:
    existing = {e.slug for e in db.query(InsuranceEntity).all()}
    created = 0
    for f in fins:
        if f.slug in existing:
            continue
        db.add(InsuranceEntity(slug=f.slug, name=f.name, entity_type="aseguradora",
                               is_active=True))
        existing.add(f.slug)
        created += 1
    return created


def _persist_entity_series(db: Session, fins, period: str, lineage: Lineage) -> int:
    """Persiste los totales por aseguradora + el desglose POR RAMO.

    El desglose usa la columna ``dimension`` que el modelo ya tiene para eso (la usan las
    series de mercado por ramo). Sin persistirlo, el loss ratio por ramo —que mide skill de
    pricing y es más difícil de maquillar que el margen agregado— no es computable aguas
    abajo aunque el catálogo lo traiga (spec §5.6).
    """
    touched = 0
    for f in fins:
        celdas = [(code, None, value) for code, value in f.as_series().items()]
        for ramo, v in (getattr(f, "por_ramo", None) or {}).items():
            celdas.append(("primas_suscritas", ramo, v.get("primas")))
            celdas.append(("siniestros_pagados", ramo, v.get("siniestros")))
        for code, dim, value in celdas:
            q = (db.query(InsuranceSeries)
                 .filter(InsuranceSeries.series_code == code,
                         InsuranceSeries.period == period,
                         InsuranceSeries.entity_slug == f.slug))
            q = (q.filter(InsuranceSeries.dimension == dim) if dim
                 else q.filter(InsuranceSeries.dimension.is_(None)))
            row = q.first()
            if row is None:
                row = InsuranceSeries(series_code=code, period=period,
                                      entity_slug=f.slug, dimension=dim)
                db.add(row)
            row.value = value
            row.unit = "RD$"
            row.frequency = "annual"
            row.source = lineage.source
            row.license = lineage.license
            row.published_at = lineage.fetched_at
            touched += 1
    return touched


def ingest_audited(db: Session, content: bytes, period: str,
                   set_phase: Optional[Callable[[str], None]] = None) -> Dict:
    """Extract an audited workbook (bytes) for *period* → roster + series + ISF."""
    set_phase = set_phase or (lambda _m: None)
    lineage = Lineage(source=_SOURCE, license=_LICENSE, fetched_at=date.today())

    set_phase(f"Extrayendo estados auditados {period}")
    fins = extract_audited_workbook(content, period)
    fins = [f for f in fins if f.reconciled]  # only balanced sheets (fail-soft)
    if not fins:
        return {"insurers": 0, "period": period, "note": "sin hojas conciliadas"}

    set_phase("Roster de aseguradoras")
    created = _seed_entities(db, fins)
    set_phase("Series por aseguradora")
    rows = _persist_entity_series(db, fins, period, lineage)
    db.flush()

    set_phase("Índice de Solidez de Aseguradora (ISF)")
    from modules.insurance_intel.scoring.batch import score_and_persist
    ratings = score_and_persist(db)

    db.commit()
    set_phase("Completado")
    return {"insurers": len(fins), "entities_created": created, "series_rows": rows,
            "period": period, "ratings_written": ratings["ratings_written"]}


def sis_financials_sync(db: Session, set_phase: Optional[Callable[[str], None]] = None,
                        year: Optional[str] = None) -> Dict:
    """Discover + download the latest audited workbook, then ingest it."""
    import requests

    set_phase = set_phase or (lambda _m: None)
    set_phase("Descubriendo estados auditados (SIS)")
    urls = discover_audited_urls()
    if not urls:
        return {"insurers": 0, "note": "no se encontraron archivos auditados en el portal"}
    target = year or max(urls)  # latest year by default
    url = urls.get(target)
    if not url:
        return {"insurers": 0, "note": f"año {target} no disponible", "available": sorted(urls)}

    set_phase(f"Descargando auditados {target}")
    r = requests.get(url, headers={"User-Agent": _UA}, timeout=90)
    r.raise_for_status()
    return ingest_audited(db, r.content, target, set_phase=set_phase)


def sis_financials_history_sync(db: Session, set_phase: Optional[Callable[[str], None]] = None,
                                since_year: int = 2018) -> Dict:
    """Ingest the HISTORY of audited statements (``since_year``..latest) → per-entity series
    with a multi-year trajectory, recomputing the ISF once at the end. Feeds the ISF backtest
    (G5). Best-effort per year; idempotent. Defaults to 2018 (the .xlsx era, stable layout)."""
    import requests

    set_phase = set_phase or (lambda _m: None)
    set_phase("Descubriendo estados auditados (SIS)")
    urls = discover_audited_urls()
    years = sorted(y for y in urls if y.isdigit() and int(y) >= since_year)
    if not years:
        return {"years": [], "note": f"sin auditados desde {since_year}"}

    lineage = Lineage(source=_SOURCE, license=_LICENSE, fetched_at=date.today())
    total_rows = created = 0
    ingested: List[str] = []
    for y in years:
        set_phase(f"Auditados {y}")
        try:
            r = requests.get(urls[y], headers={"User-Agent": _UA}, timeout=90)
            r.raise_for_status()
            fins = [f for f in extract_audited_workbook(r.content, y) if f.reconciled]
        except Exception as e:  # noqa: BLE001 — un año que falle no tumba la historia
            logger.warning("[SIS] auditados %s no ingeridos: %s", y, e)
            continue
        if not fins:
            continue
        created += _seed_entities(db, fins)
        total_rows += _persist_entity_series(db, fins, y, lineage)
        ingested.append(y)
        db.flush()

    set_phase("Recalculando ISF (última corrida)")
    from modules.insurance_intel.scoring.batch import score_and_persist
    ratings = score_and_persist(db)
    db.commit()
    return {"years": ingested, "entities_created": created, "series_rows": total_rows,
            "ratings_written": ratings["ratings_written"]}
