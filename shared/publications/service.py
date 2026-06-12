"""Orchestration + queries for BCRD publications.

Pipeline per edition: resolve the CDN URL (probe candidates) → download →
extract text → AI digest → upsert a :class:`Publication`. Query helpers feed the
macro/banking insight engines and the Publicaciones view.
"""
from __future__ import annotations

import logging
import os
from datetime import date
from typing import Any, Callable, Dict, List, Optional, Tuple

from sqlalchemy.orm import Session

from shared.publications import catalog, digest as digest_mod
from shared.publications.fetcher import download_pdf, url_exists
from shared.publications.models import Publication

logger = logging.getLogger("sdq.publications.service")

# Injectable seams so tests don't hit the network / Anthropic.
ProbeFn = Callable[[str], bool]
DownloadFn = Callable[[str], str]
ExtractFn = Callable[[str], str]
DigestFn = Callable[[str, str, str, tuple], Dict[str, Any]]


def resolve_latest_url(
    report_key: str,
    today: Optional[date] = None,
    lookback_years: int = 2,
    probe: ProbeFn = url_exists,
) -> Optional[Tuple[str, str]]:
    """Return the newest available (period, url) for *report_key*, or None.

    Probes candidate URLs newest-first across the current year back through
    ``lookback_years``; returns the first that exists.
    """
    year = (today or _today()).year
    for period, url in catalog.candidate_urls(report_key, year, lookback_years):
        if probe(url):
            return period, url
    return None


def ingest_report(
    db: Session,
    report_key: str,
    period: Optional[str] = None,
    url: Optional[str] = None,
    *,
    force: bool = False,
    probe: ProbeFn = url_exists,
    download: DownloadFn = download_pdf,
    extract: Optional[ExtractFn] = None,
    make_digest: Optional[DigestFn] = None,
    today: Optional[date] = None,
) -> Optional[Publication]:
    """Ingest one edition of *report_key*.

    If *period*/*url* are omitted, resolves the latest available edition. Skips
    work when that (report, period) is already stored ``ok`` unless *force*.
    Returns the upserted row, or None when nothing is available to ingest.
    """
    if report_key not in catalog.REPORTS:
        raise ValueError(f"Informe desconocido: {report_key}")
    spec = catalog.REPORTS[report_key]

    if url is None or period is None:
        found = resolve_latest_url(report_key, today=today, probe=probe)
        if found is None:
            logger.info("[publications] sin edición disponible para %s", report_key)
            return None
        period, url = found

    existing = (
        db.query(Publication)
        .filter_by(report_key=report_key, period=period)
        .first()
    )
    if existing and existing.status == "ok" and not force:
        return existing

    row = existing or Publication(report_key=report_key, period=period)
    row.report_name = spec.name
    row.title = f"{spec.name} — {period}"
    row.source_url = url
    row.landing_url = spec.landing_url
    row.sectors = list(spec.sectors)
    row.status = "pending"
    row.error = None
    if existing is None:
        db.add(row)

    extract = extract or _default_extract
    make_digest = make_digest or _default_digest
    try:
        path = download(url)
        try:
            text = extract(path)
        finally:
            _safe_unlink(path)
        row.raw_text = text[:200_000]
        row.digest = make_digest(text, spec.name, period, spec.sectors)
        row.status = "ok"
    except Exception as e:  # noqa: BLE001 — record the failure, don't crash the batch
        logger.warning("[publications] fallo al ingerir %s %s: %s", report_key, period, e)
        row.status = "error"
        row.error = str(e)[:500]

    db.commit()
    db.refresh(row)
    return row


def ingest_all_latest(db: Session, **kwargs) -> List[Publication]:
    """Ingest the latest edition of every catalog report. Returns the rows touched."""
    out: List[Publication] = []
    for key in catalog.report_keys():
        row = ingest_report(db, key, **kwargs)
        if row is not None:
            out.append(row)
    return out


# ── Queries ───────────────────────────────────────────────────────
def list_publications(db: Session, report_key: Optional[str] = None) -> List[Publication]:
    q = db.query(Publication)
    if report_key:
        q = q.filter_by(report_key=report_key)
    return q.order_by(Publication.period.desc(), Publication.report_key.asc()).all()


def get_publication(db: Session, pub_id: str) -> Optional[Publication]:
    return db.query(Publication).filter_by(id=pub_id).first()


def publication_prompt_context(
    db: Session, sector: Optional[str] = None, max_findings: int = 3
) -> List[Dict[str, Any]]:
    """Compact, prompt-ready digest blocks to enrich an LLM insight.

    Trims each latest digest (filtered by *sector*) to the essentials so it can be
    inlined into a narrative prompt without bloating it. Empty when nothing fits.
    """
    out: List[Dict[str, Any]] = []
    for d in get_latest_digests(db, sector=sector):
        dg = d.get("digest") or {}
        if not (dg.get("resumen") or dg.get("hallazgos")):
            continue
        out.append({
            "informe": d["report_name"],
            "periodo": d["period"],
            "resumen": dg.get("resumen", ""),
            "hallazgos": (dg.get("hallazgos") or [])[:max_findings],
            "cifras": (dg.get("cifras") or [])[: max_findings + 1],
            "riesgos": (dg.get("riesgos") or [])[:max_findings],
            "fuente": d.get("source_url", ""),
        })
    return out


def get_latest_digests(
    db: Session, sector: Optional[str] = None, limit_per_report: int = 1
) -> List[Dict[str, Any]]:
    """Compact latest digests for insight enrichment.

    One (or ``limit_per_report``) most-recent ``ok`` edition per report, filtered
    to those whose catalog ``sectors`` include *sector* (when given). Returns small
    dicts safe to inline into an LLM prompt — no raw text.
    """
    out: List[Dict[str, Any]] = []
    for key, spec in catalog.REPORTS.items():
        if sector and sector not in spec.sectors:
            continue
        rows = (
            db.query(Publication)
            .filter_by(report_key=key, status="ok")
            .order_by(Publication.period.desc())
            .limit(limit_per_report)
            .all()
        )
        for r in rows:
            out.append({
                "report_key": r.report_key,
                "report_name": r.report_name,
                "period": r.period,
                "source_url": r.source_url,
                "digest": r.digest or {},
            })
    return out


# ── Defaults (kept thin so they can be swapped in tests) ──────────
def _default_extract(path: str) -> str:  # pragma: no cover - thin I/O wrapper
    from shared.pdf import extract_pdf_text

    return extract_pdf_text(path)


def _default_digest(text: str, report_name: str, period: str, sectors: tuple) -> Dict[str, Any]:  # pragma: no cover - AI
    return digest_mod.build_digest(text, report_name, period, sectors)


def _today() -> date:  # pragma: no cover - trivial seam for tests
    return date.today()


def _safe_unlink(path: str) -> None:
    try:
        os.unlink(path)
    except OSError:
        pass
