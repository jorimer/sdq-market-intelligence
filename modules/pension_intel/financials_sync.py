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
from typing import Callable, Dict, List, Optional

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
_SITE = "https://sipen.gob.do"
# Verified site structure (live probe 2026-06-27): the estados-financieros portal is a
# 4-level hierarchy, NOT a flat landing — AFP index → per-AFP page → per-year page →
# the actual /descarga/ files (scanned monthly PDFs). Per-AFP attribution comes from the
# PATH (reliable), and the period from the file's "_YYYY_MM_" timestamp suffix. The files
# are named "<afp-token>-<year>_<YYYY>_<MM>_<ts>.pdf" — they do NOT contain the literal
# "estados-financieros", so file discovery keys on /descarga/ + the period stamp only.
EF_AFP_INDEX = f"{_SITE}/estadisticas/estados-financieros-afp/estados-financieros"
_FILE_RE = re.compile(r"/descarga/[^\"'> ]+\.(?:pdf|xlsx)", re.IGNORECASE)
_PERIOD_RE = re.compile(r"_(\d{4})_(\d{2})_")


def _abs(url: str) -> str:
    return url if url.startswith("http") else _SITE + url


def _afp_token(slug: str) -> str:
    """Our slug → the site's path token: afp_jmmb_bdi → afp-jmmb-bdi."""
    return "afp-" + slug[len("afp_"):].replace("_", "-")


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
# Pure HTML parsers (offline-testable); the orchestrator does the network I/O.

def afp_page_links(index_html: str) -> Dict[str, str]:
    """``{afp_slug: url}`` of the per-AFP pages, from the estados-financieros index.

    Keys only AFPs in our catalog (site token afp-jmmb-bdi → slug afp_jmmb_bdi). The
    URL is built from the verified index path, so it's independent of relative/abs hrefs."""
    known = {_afp_token(slug): slug for slug, _ in afp_catalog()}
    out: Dict[str, str] = {}
    for token in re.findall(r"/estados-financieros/(afp-[a-z0-9-]+)", index_html, re.IGNORECASE):
        slug = known.get(token.lower())
        if slug:
            out[slug] = f"{EF_AFP_INDEX}/{token.lower()}"
    return out


def year_links(afp_html: str, token: str) -> Dict[int, str]:
    """``{year: url}`` of the per-year sub-pages on an AFP page (e.g. .../afp-popular-2026)."""
    out: Dict[int, str] = {}
    pat = re.compile(rf'["\']([^"\']*/{re.escape(token)}/[^"\']*?(20\d{{2}}))["\']', re.IGNORECASE)
    for url, year in pat.findall(afp_html):
        out[int(year)] = _abs(url)
    return out


def file_links(year_html: str) -> Dict[str, str]:
    """``{period "YYYY-MM": url}`` of the /descarga/ statement files on a per-year page.

    The latest file per period wins (timestamped). Files without a "_YYYY_MM_" stamp are
    skipped (we never guess a period)."""
    out: Dict[str, str] = {}
    for raw in _FILE_RE.findall(year_html):
        m = _PERIOD_RE.search(raw)
        if m:
            out[f"{m.group(1)}-{m.group(2)}"] = _abs(raw)
    return out


def sipen_financials_sync(
    db: Session, set_phase: Optional[Callable[[str], None]] = None,
    only_latest: bool = True,
) -> Dict:  # pragma: no cover - network I/O (verifies on Railway)
    """LIVE: crawl SIPEN's estados-financieros hierarchy and ingest each AFP's statement.

    For each AFP: latest-year page → its files. ``only_latest`` (default) ingests just the
    most recent month per AFP; otherwise every month of the latest year. Per-AFP attribution
    is by PATH (reliable). A failed file/AFP never aborts the run. Runs from Railway (static
    egress IPs + browser UA pass SIPEN's bot wall)."""
    import httpx

    set_phase = set_phase or (lambda _m: None)
    sipen_client.check_license()
    set_phase("Descubriendo AFP (SIPEN)")
    errors: List[str] = []
    ingested = 0
    try:
        with httpx.Client(timeout=90, headers=_BROWSER_HEADERS, follow_redirects=True) as http:
            afps = afp_page_links(http.get(EF_AFP_INDEX).text)
            if not afps:
                return {"error": "no se descubrieron páginas de AFP en el índice de SIPEN",
                        "ingested": 0, "errors": []}
            names = {slug: name for slug, name in afp_catalog()}
            for slug, afp_url in afps.items():
                try:
                    years = year_links(http.get(afp_url).text, _afp_token(slug))
                    if not years:
                        errors.append(f"{slug}: sin años")
                        continue
                    files = file_links(http.get(years[max(years)]).text)
                    if not files:
                        errors.append(f"{slug}: sin archivos en {max(years)}")
                        continue
                    periods = sorted(files)
                    chosen = periods[-1:] if only_latest else periods
                    for period in chosen:
                        url = files[period]
                        set_phase(f"{names[slug]} · {period}")
                        content = http.get(url).content
                        ingest_financials(db, slug, content, url.rsplit("/", 1)[-1],
                                          set_phase=set_phase)
                        ingested += 1
                except Exception as e:  # noqa: BLE001 — best-effort per AFP
                    errors.append(f"{slug}: {e}")
    except Exception as e:  # noqa: BLE001
        return {"error": str(e), "ingested": ingested, "errors": errors}
    return {"ingested": ingested, "errors": errors}
