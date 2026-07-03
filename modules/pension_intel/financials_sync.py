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
_SITE = "https://sipen.gob.do"
# Verified site structure (live probe 2026-06-27): the estados-financieros portal is a
# 4-level hierarchy, NOT a flat landing — AFP index → per-AFP page → per-year page →
# the actual /descarga/ files (scanned monthly PDFs). Per-AFP attribution comes from the
# PATH (reliable), and the period from the file's "_YYYY_MM_" timestamp suffix. The files
# are named "<afp-token>-<year>_<YYYY>_<MM>_<ts>.pdf" — they do NOT contain the literal
# "estados-financieros", so file discovery keys on /descarga/ + the period stamp only.
EF_AFP_INDEX = f"{_SITE}/estadisticas/estados-financieros-afp/estados-financieros"
# The AUDITED section (owner-designated authoritative source, confirmed live via
# sipen-audited-probe 2026-07-03): monthly statements 2010-2026 per AFP, 12/year, same
# AFP→year→/descarga hierarchy as the interim index. The per-AFP page URL is built from the
# token (the interim ``afp_page_links`` regex keys ``/estados-financieros/`` and does NOT
# match the ``-auditados`` path), so we iterate the catalog rather than parse the index.
EF_AUDITED_INDEX = f"{_SITE}/estadisticas/estados-financieros-afp/estados-financieros-auditados"
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
    recompute: bool = True,
) -> Dict:
    """Extract one AFP statement (PDF/XLSX) → persist patrimonio/activos → recompute ISA.

    ``recompute=False`` skips the (expensive) ISA rescore — for BATCH history ingest, where
    the caller recomputes ONCE after persisting every period (see
    ``sipen_financials_history_sync``). The series are still committed per file so a failure
    mid-batch never loses the work already done."""
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
    # AUM (administered funds) → the ISA's escala/costo dimensions. Real figure from the
    # statement itself, so all AFPs share one consistent source (peer-normalized → unit-invariant).
    if fields.get("fondos_administrados") is not None:
        _upsert_series(db, afp_slug, "fondos_administrados", period, fields["fondos_administrados"], "RD$")
    # Commission revenue for the ISA cost dimension — same statement as AUM → RD$ units
    # and the same period, replacing the orphaned static 'RD$ MM' SIPEN series.
    if fields.get("comisiones") is not None:
        _upsert_series(db, afp_slug, "comisiones_anual", period, fields["comisiones"], "RD$")

    db.flush()
    ratings_written = None
    if recompute:
        set_phase("Recalculando ISA (con solvencia)")
        from modules.pension_intel.scoring.batch import score_and_persist
        ratings_written = score_and_persist(db)["ratings_written"]
    db.commit()
    return {
        "afp": names[afp_slug], "period": period,
        "patrimonio": fields["patrimonio"], "activos_totales": fields["activos_totales"],
        "ratings_written": ratings_written,
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


def latest_statement_url(slug: str) -> Optional[Tuple[str, str]]:  # pragma: no cover - network I/O
    """``(period, url)`` of the most recent estados-financieros file for an AFP, or None."""
    import httpx

    token = _afp_token(slug)
    afp_url = f"{EF_AFP_INDEX}/{token}"
    with httpx.Client(timeout=60, headers=_BROWSER_HEADERS, follow_redirects=True) as http:
        years = year_links(http.get(afp_url).text, token)
        if not years:
            return None
        files = file_links(http.get(years[max(years)]).text)
        if not files:
            return None
        period = sorted(files)[-1]
        return period, files[period]


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


def _afp_audited_url(slug: str) -> str:
    return f"{EF_AUDITED_INDEX}/{_afp_token(slug)}"


def select_history_periods(
    year_files: Dict[int, Dict[str, str]], since_year: int, annual: bool,
) -> Dict[str, str]:
    """Pure period selection for the history ingest → ``{period 'YYYY-MM': url}``.

    *year_files* = ``{year: {period: url}}`` (from ``file_links`` per year page). When
    *annual*, pick the **December** close of each year ≥ *since_year* PLUS the single most
    recent month across all years (freshness — kept even if it isn't a December). When not
    *annual*, take every month of every year ≥ *since_year*. Pure (no network) → unit-tested."""
    chosen: Dict[str, str] = {}
    latest_period: Optional[str] = None
    latest_url: Optional[str] = None
    for year in sorted(year_files):
        if year < since_year:
            continue
        files = year_files[year]
        for period, url in files.items():
            if latest_period is None or period > latest_period:
                latest_period, latest_url = period, url
        if annual:
            dec = f"{year}-12"
            if dec in files:
                chosen[dec] = files[dec]
        else:
            chosen.update(files)
    if latest_period and latest_period not in chosen and latest_url:
        chosen[latest_period] = latest_url
    return chosen


def sipen_financials_history_sync(
    db: Session, set_phase: Optional[Callable[[str], None]] = None,
    since_year: int = 2010, annual: bool = True,
) -> Dict:  # pragma: no cover - network I/O (verifies on Railway)
    """LIVE: ingest the AUDITED estados-financieros HISTORY per AFP → solvency trajectory.

    Per AFP, crawl every year ≥ *since_year* from the audited section and choose, when
    ``annual`` (default), the **December** close of each year (the year-end audited statement)
    plus the single most-recent month available (freshness). ``annual=False`` ingests every
    month found. Each file is extracted + persisted with ``recompute=False``; the ISA is
    rescored ONCE at the end. Best-effort: a failed file/year/AFP never aborts the run. Runs
    from Railway (static egress + browser UA). Idempotent (upsert by period)."""
    import httpx

    set_phase = set_phase or (lambda _m: None)
    sipen_client.check_license()
    names = {slug: name for slug, name in afp_catalog()}
    ingested = 0
    errors: List[str] = []
    periods_by_afp: Dict[str, List[str]] = {}

    with httpx.Client(timeout=120, headers=_BROWSER_HEADERS, follow_redirects=True) as http:
        for slug, name in afp_catalog():
            token = _afp_token(slug)
            try:
                years = year_links(http.get(_afp_audited_url(slug)).text, token)
            except Exception as e:  # noqa: BLE001 — best-effort per AFP
                errors.append(f"{slug}: página AFP {e}")
                continue
            # Fetch each year's file list, then choose the periods (pure selection).
            year_files: Dict[int, Dict[str, str]] = {}
            for y in sorted(years):
                if y < since_year:
                    continue
                try:
                    year_files[y] = file_links(http.get(years[y]).text)  # {period: url}
                except Exception as e:  # noqa: BLE001
                    errors.append(f"{slug} {y}: {e}")
            chosen = select_history_periods(year_files, since_year, annual)

            for period in sorted(chosen):
                set_phase(f"{name} · {period}")
                try:
                    content = http.get(chosen[period]).content
                    ingest_financials(db, slug, content, chosen[period].rsplit("/", 1)[-1],
                                      set_phase=set_phase, recompute=False)
                    ingested += 1
                    periods_by_afp.setdefault(slug, []).append(period)
                except Exception as e:  # noqa: BLE001 — best-effort per file
                    errors.append(f"{slug} {period}: {e}")

    # Single ISA rescore after the whole batch (solvency now has audited history).
    set_phase("Recalculando ISA (solvencia auditada · historia)")
    from modules.pension_intel.scoring.batch import score_and_persist
    ratings = score_and_persist(db)
    db.commit()
    return {
        "ingested": ingested,
        "periods_por_afp": {names.get(s, s): sorted(p) for s, p in periods_by_afp.items()},
        "ratings_written": ratings.get("ratings_written"),
        "n_errors": len(errors),
        "errors": errors[:50],
    }
