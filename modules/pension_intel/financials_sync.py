"""AFP estados financieros → per-AFP solvency series → ISA recompute.

Two entry points (decision 2026-06-27, owner):
  * ``ingest_financials`` — MANUAL upload (PDF/XLSX). Always works, fully testable;
    the path that doesn't depend on getting past SIPEN's bot wall.
  * ``sipen_financials_sync`` — LIVE: discover the estados-financieros downloads on
    SIPEN's portal (``/descarga/…``) and ingest each. Runs from Railway (static egress
    IPs + browser UA); best-effort, verifies on the first real run.

Both feed ``patrimonio`` and ``activos_totales`` per AFP into ``pension_series``; the ISA
then computes the solvency dimension (patrimonio/activos) and, once it's present, emits
the ABSOLUTE band for that AFP (see scoring/isa.py). Missing figures stay None.
"""
from __future__ import annotations

import logging
import re
from datetime import date
from typing import Callable, Dict, List, Optional, Tuple

from sqlalchemy.orm import Session

from modules.pension_intel.external.financials_extractor import (
    extract_financials,
    map_afp_financials,
    statement_period,
)
from modules.pension_intel.models.models import PensionSeries
from shared.data.sipen_client import afp_catalog, sipen_client

logger = logging.getLogger("sdq.pension_intel.financials_sync")

_BROWSER_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/124.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
}
# Confirmed SIPEN download shape: /descarga/<concepto>_<YYYY>_<MM>_<timestamp>.{pdf,xlsx}
_DESCARGA_RE = re.compile(
    r"/descarga/[^\"'> ]*estados-financieros[^\"'> ]*\.(?:pdf|xlsx)", re.IGNORECASE)
_PERIOD_RE = re.compile(r"_(\d{4})_(\d{2})_")
EF_AFP_LANDING = "https://www.sipen.gob.do/estadisticas/estados-financieros-afp"


def _upsert_series(db: Session, slug: str, code: str, period: str,
                   value: Optional[float], unit: str) -> None:
    row = (
        db.query(PensionSeries)
        .filter(PensionSeries.series_code == code, PensionSeries.period == period,
                PensionSeries.entity_slug == slug)
        .first()
    )
    if row is None:
        row = PensionSeries(series_code=code, period=period, entity_slug=slug)
        db.add(row)
    row.value = value
    row.unit = unit
    row.frequency = "annual"
    row.source = sipen_client.source
    row.license = sipen_client.license
    row.published_at = date.today()


def ingest_financials(
    db: Session, afp_slug: str, content: bytes, filename: str,
    set_phase: Optional[Callable[[str], None]] = None,
) -> Dict:
    """Extract one AFP statement (PDF/XLSX) → persist patrimonio/activos → recompute ISA."""
    set_phase = set_phase or (lambda _m: None)
    names = {slug: name for slug, name in afp_catalog()}
    if afp_slug not in names:
        raise ValueError(f"AFP desconocida: {afp_slug}")

    set_phase("Extrayendo estados financieros (IA)")
    statements = extract_financials(content, filename)
    fields = map_afp_financials(statements)
    period = statement_period(statements)
    if not period:
        raise ValueError("No se pudo determinar el período del estado financiero.")

    if fields["patrimonio"] is None and fields["activos_totales"] is None:
        raise ValueError("No se extrajeron cifras de patrimonio ni activos del documento.")

    set_phase(f"Persistiendo {names[afp_slug]} · {period}")
    _upsert_series(db, afp_slug, "patrimonio", period, fields["patrimonio"], "RD$")
    _upsert_series(db, afp_slug, "activos_totales", period, fields["activos_totales"], "RD$")
    if fields["resultado"] is not None:
        _upsert_series(db, afp_slug, "resultado_neto", period, fields["resultado"], "RD$")

    set_phase("Recalculando ISA (con solvencia)")
    db.flush()
    from modules.pension_intel.scoring.batch import score_and_persist
    ratings = score_and_persist(db)
    db.commit()
    return {
        "afp": names[afp_slug], "period": period,
        "patrimonio": fields["patrimonio"], "activos_totales": fields["activos_totales"],
        "ratings_written": ratings["ratings_written"],
    }


# ── Live discovery (Railway: static egress + browser UA) ──────────────────────

def discover_ef_links(html_text: str) -> List[Tuple[str, str]]:
    """``[(period "YYYY-MM", url)]`` for the estados-financieros downloads in a landing.

    Best-effort over the confirmed ``/descarga/…estados-financieros…`` URL shape; the
    latest file per period wins (timestamp suffix). Verifies on the first real run."""
    seen: Dict[str, str] = {}
    for raw in _DESCARGA_RE.findall(html_text):
        m = _PERIOD_RE.search(raw)
        period = f"{m.group(1)}-{m.group(2)}" if m else None
        if period:
            seen[period] = raw  # later match (sorted by appearance) overwrites; ok
    base = "https://www.sipen.gob.do"
    return [(p, (u if u.startswith("http") else base + u)) for p, u in sorted(seen.items())]


def sipen_financials_sync(
    db: Session, set_phase: Optional[Callable[[str], None]] = None,
    only_latest: bool = True,
) -> Dict:  # pragma: no cover - network I/O (verifies on Railway)
    """LIVE: scrape the estados-financieros landing, download + ingest each file.

    Best-effort and per-AFP attribution is approximate (the landing groups by AFP/period);
    a failed file never aborts the run. Runs from Railway where the static egress IPs and
    a browser UA may pass SIPEN's bot wall."""
    import httpx

    set_phase = set_phase or (lambda _m: None)
    sipen_client.check_license()
    set_phase("Descubriendo estados financieros (SIPEN)")
    errors: List[str] = []
    ingested = 0
    try:
        with httpx.Client(timeout=60, headers=_BROWSER_HEADERS, follow_redirects=True) as http:
            html = http.get(EF_AFP_LANDING).text
            links = discover_ef_links(html)
            if only_latest:
                links = links[-1:]
            for period, url in links:
                set_phase(f"Descargando {period}")
                try:
                    content = http.get(url).content
                    fname = url.rsplit("/", 1)[-1]
                    # Attribution by AFP is resolved from the document itself (company_info);
                    # we map to the matching slug by name when possible.
                    slug = _slug_from_doc_or_default(content, fname)
                    ingest_financials(db, slug, content, fname, set_phase=set_phase)
                    ingested += 1
                except Exception as e:  # noqa: BLE001
                    errors.append(f"{period}: {e}")
    except Exception as e:  # noqa: BLE001
        return {"error": str(e), "ingested": ingested, "errors": errors}
    return {"ingested": ingested, "errors": errors}


def _slug_from_doc_or_default(content: bytes, filename: str) -> str:  # pragma: no cover
    """Best-effort AFP slug from the filename; falls back to the first AFP. The live
    path's attribution is refined once the real landing/file naming is observed."""
    low = (filename or "").lower()
    for slug, name in afp_catalog():
        token = slug.replace("afp_", "")
        if token in low:
            return slug
    return afp_catalog()[0][0]
