"""SIPEN bulletins → monthly unit value (valor cuota / NAV) → pension_series.

Builds the per-AFP monthly NAV series by chaining consecutive Boletines Trimestrales
(each carries three months in Cuadro 6.4). This is the raw input for the ISA *riesgo*
dimension: monthly NAV → monthly returns → realized volatility. Persisted as
``valor_cuota`` per-AFP ``PensionSeries`` (period ``YYYY-MM``), so the scorer reads it like
any other series.

Two entry points (mirrors ``cartera_sync``):
  * ``ingest_valor_cuota`` — MANUAL upload of one bulletin PDF (always works, testable).
  * ``sipen_nav_sync`` — LIVE: fetch the latest N bulletins, extract Cuadro 6.4, persist.

Best-effort per bulletin: a failed download/parse never aborts the others (the series just
keeps the months it did get). Missing values stay absent — never an invented NAV.
"""
from __future__ import annotations

import logging
from datetime import date
from typing import Callable, Dict, List, Optional, Tuple

from sqlalchemy.orm import Session

from modules.pension_intel.external.nav_extractor import (
    extract_valor_cuota_from_pdf,
    parse_valor_cuota_text,
)
from modules.pension_intel.models.models import PensionSeries
from shared.data.sipen_client import sipen_client

logger = logging.getLogger("sdq.pension_intel.nav_sync")

VALOR_CUOTA_CODE = "valor_cuota"
# Bulletins to pull for the realized-vol window: 30 clean months (owner decision
# 2026-07-01) ≈ 10 quarters; +1 for headroom / the extra month a return needs.
_DEFAULT_BOLETINES = 11


def _upsert_nav(db: Session, slug: str, period: str, nav: float) -> bool:
    """Upsert one NAV point. Returns True if a row was created."""
    row = (
        db.query(PensionSeries)
        .filter(PensionSeries.series_code == VALOR_CUOTA_CODE,
                PensionSeries.period == period,
                PensionSeries.entity_slug == slug)
        .first()
    )
    created = row is None
    if row is None:
        row = PensionSeries(series_code=VALOR_CUOTA_CODE, period=period, entity_slug=slug)
        db.add(row)
    row.value = nav
    row.unit = "RD$ (base 100 = 2003)"
    row.frequency = "monthly"
    row.source = sipen_client.source
    row.license = sipen_client.license
    row.published_at = date.today()
    return created


def persist_valor_cuota(db: Session, per_afp: Dict[str, List[Tuple[str, float]]]) -> Dict:
    """Upsert every (AFP, period) NAV point. Returns ``{points, periods, afps}``."""
    points = 0
    periods = set()
    for slug, obs in per_afp.items():
        for period, nav in obs:
            _upsert_nav(db, slug, period, nav)
            points += 1
            periods.add(period)
    return {"points": points, "periods": sorted(periods), "afps": sorted(per_afp)}


def ingest_valor_cuota(db: Session, content: bytes,
                       set_phase: Optional[Callable[[str], None]] = None) -> Dict:
    """Extract one bulletin's Cuadro 6.4 (valor cuota) → persist → commit."""
    set_phase = set_phase or (lambda _m: None)
    set_phase("Extrayendo Cuadro 6.4 (valor cuota)")
    per_afp = extract_valor_cuota_from_pdf(content)
    if not per_afp:
        return {"points": 0, "periods": [], "afps": [], "error": "no se halló el Cuadro 6.4"}
    res = persist_valor_cuota(db, per_afp)
    db.commit()
    return res


def sipen_nav_sync(db: Session, set_phase: Optional[Callable[[str], None]] = None,
                   n_boletines: int = _DEFAULT_BOLETINES) -> Dict:  # pragma: no cover - network I/O
    """LIVE: fetch the latest *n_boletines* Boletines Trimestrales, extract Cuadro 6.4 and
    persist the monthly NAV series. Best-effort per bulletin."""
    import httpx

    from shared.data.sipen_client import (
        _BOLETIN_PAGE, _CKAN_HEADERS, boletin_pdf_links)

    set_phase = set_phase or (lambda _m: None)
    sipen_client.check_license()
    set_phase("Descubriendo boletines (SIPEN)")
    all_points = 0
    periods = set()
    afps = set()
    errors: List[str] = []
    with httpx.Client(timeout=90, headers=_CKAN_HEADERS, follow_redirects=True) as http:
        links = boletin_pdf_links(http.get(_BOLETIN_PAGE).text)
        if not links:
            return {"points": 0, "periods": [], "afps": [], "boletines": 0,
                    "errors": ["no se descubrió ningún boletín"]}
        latest = sorted(links, key=lambda t: t[0], reverse=True)[:n_boletines]
        done = 0
        for num, url in latest:
            set_phase(f"Boletín No. {num} ({done + 1}/{len(latest)})")
            try:
                per_afp = parse_valor_cuota_text(_extract_text(http.get(url).content))
                if not per_afp:
                    errors.append(f"bol {num}: sin Cuadro 6.4")
                    continue
                res = persist_valor_cuota(db, per_afp)
                db.commit()
                all_points += res["points"]
                periods.update(res["periods"])
                afps.update(res["afps"])
                done += 1
            except Exception as e:  # noqa: BLE001 — un boletín no aborta los demás
                db.rollback()
                errors.append(f"bol {num}: {e}")
    return {"points": all_points, "periods": sorted(periods), "afps": sorted(afps),
            "boletines": done, "errors": errors}


def _extract_text(content: bytes) -> str:  # pragma: no cover - thin wrapper over I/O
    import io

    from pdfminer.high_level import extract_text

    return extract_text(io.BytesIO(content))
