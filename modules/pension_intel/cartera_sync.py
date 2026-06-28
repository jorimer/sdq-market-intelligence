"""SIPEN bulletin → pension investment portfolio (cartera) → pension_holdings.

Two entry points (mirrors financials_sync):
  * ``ingest_cartera`` — MANUAL upload of a bulletin PDF (always works, testable).
  * ``sipen_cartera_sync`` — LIVE: discover the latest Boletín Trimestral on SIPEN,
    extract Cuadro 6.1, persist the holdings.

Persists the "Subtotal Fondos CCI" column (the system portfolio) keyed by issuer, with
the structural sub-sector grouping and the Macro cross-key (Hacienda → deuda pública,
BCRD). The extractor reconciles the leaves to the table TOTAL or fails closed, so we
never persist unverified figures. Missing amounts stay NULL.
"""
from __future__ import annotations

import logging
from datetime import date
from typing import Callable, Dict, Optional

from sqlalchemy.orm import Session

from modules.pension_intel.external.cartera_extractor import (
    Holding,
    extract_cartera_from_pdf,
)
from modules.pension_intel.models.models import PensionHolding
from shared.data.sipen_client import fetch_latest_boletin, sipen_client

logger = logging.getLogger("sdq.pension_intel.cartera_sync")

_FUND_CCI = "cci"


def _upsert_holding(db: Session, period: str, h: Holding) -> None:
    row = (
        db.query(PensionHolding)
        .filter(PensionHolding.period == period, PensionHolding.fund == _FUND_CCI,
                PensionHolding.issuer_slug == h.issuer_slug)
        .first()
    )
    if row is None:
        row = PensionHolding(period=period, fund=_FUND_CCI, issuer_slug=h.issuer_slug)
        db.add(row)
    row.sub_sector = h.sub_sector
    row.issuer = h.issuer
    row.amount = h.amount
    row.pct = h.pct
    row.is_subtotal = h.is_subtotal
    row.macro_class = h.macro_class
    row.source = sipen_client.source
    row.license = sipen_client.license
    row.published_at = date.today()


def persist_cartera(db: Session, period: str, holdings) -> int:
    """Upsert all holdings for a period (CCI fund). Returns rows touched."""
    touched = 0
    for h in holdings:
        _upsert_holding(db, period, h)
        touched += 1
    return touched


def ingest_cartera(
    db: Session, content: bytes, filename: str = "boletin.pdf",
    set_phase: Optional[Callable[[str], None]] = None,
) -> Dict:
    """Extract one bulletin's Cuadro 6.1 → persist pension_holdings → commit."""
    set_phase = set_phase or (lambda _m: None)
    set_phase("Extrayendo Cuadro 6.1 (cartera)")
    period, holdings = extract_cartera_from_pdf(content)
    set_phase(f"Persistiendo cartera · {period}")
    touched = persist_cartera(db, period, holdings)
    db.commit()
    return {"period": period, "holdings": touched,
            "issuers": sum(1 for h in holdings if not h.is_subtotal)}


def sipen_cartera_sync(
    db: Session, set_phase: Optional[Callable[[str], None]] = None,
) -> Dict:  # pragma: no cover - network I/O (verifies on Railway)
    """LIVE: fetch the latest Boletín Trimestral, extract Cuadro 6.1, persist holdings."""
    set_phase = set_phase or (lambda _m: None)
    sipen_client.check_license()
    set_phase("Descubriendo boletín (SIPEN)")
    found = fetch_latest_boletin()
    if not found:
        return {"error": "no se descubrió ningún boletín trimestral", "holdings": 0}
    num, content = found
    set_phase(f"Boletín No. {num}")
    result = ingest_cartera(db, content, f"boletin-{num}.pdf", set_phase=set_phase)
    result["boletin"] = num
    logger.info("[SIPEN] cartera boletín %s · %s · %s holdings",
                num, result["period"], result["holdings"])
    return result
