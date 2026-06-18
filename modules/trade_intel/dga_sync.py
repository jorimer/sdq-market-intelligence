"""DGA trade sync — ingest real customs trade-by-chapter into ``trade_intel``.

Scrapes the DGA institutional pages for the quarterly Data-Cruda chapter files
(exports + imports), downloads + parses each, and persists one trade snapshot per
quarter (flows by HS chapter → resilience score). Real public data; best-effort —
an upstream failure reports, never crashes the operation.

Values are stored in **USD millions** (the file is raw USD; the score is share-
based so unaffected, but the UI expects millions). ``source="DGA"``.
"""
import logging
from typing import Callable, Dict, List, Optional

from sqlalchemy.orm import Session

from modules.trade_intel.service import compute_and_persist
from shared.data.dga_client import (
    EXPORTS_LANDING,
    IMPORTS_LANDING,
    dga_client,
    discover_dc_files,
    parse_chapter_xlsx,
)

logger = logging.getLogger("sdq.trade_intel.dga_sync")

_USD_TO_MILLIONS = 1_000_000.0


def _flows_for(content: bytes, direction: str, period: str) -> List[Dict]:
    rows = parse_chapter_xlsx(content)
    return [
        {
            "product": desc or f"Capítulo {code}",
            "direction": direction,
            "value": round(fob / _USD_TO_MILLIONS, 4),
            "period": period,
            "partner": None,
            "unit": "USD millones",
            "source": dga_client.source,
            "license": dga_client.license,
        }
        for code, desc, fob in rows
    ]


def dga_trade_sync(
    db: Session,
    set_phase: Optional[Callable[[str], None]] = None,
    only_latest: bool = False,
) -> Dict:
    """Ingest DGA customs trade by chapter → one snapshot per quarter.

    *only_latest* ingests just the most recent quarter (a light refresh);
    otherwise it backfills every quarter the DGA publishes."""
    set_phase = set_phase or (lambda _m: None)
    dga_client.check_license()

    import httpx

    set_phase("descubriendo archivos de Aduanas (export + import)")
    try:
        with httpx.Client(timeout=60, follow_redirects=True,
                          headers={"User-Agent": "Mozilla/5.0 (SDQ-MIP)"}) as http:
            exp = discover_dc_files(http.get(EXPORTS_LANDING).text, "export")
            imp = discover_dc_files(http.get(IMPORTS_LANDING).text, "import")
            periods = sorted(set(exp) | set(imp))
            if only_latest and periods:
                periods = periods[-1:]
            if not periods:
                return {"error": "Aduanas: no se encontraron archivos Data Cruda",
                        "periods": [], "errors": ["sin archivos"]}

            ingested: List[str] = []
            errors: List[str] = []
            for i, period in enumerate(periods, 1):
                set_phase(f"Aduanas {period} ({i}/{len(periods)})")
                try:
                    flows: List[Dict] = []
                    for direction, urls in (("export", exp), ("import", imp)):
                        url = urls.get(period)
                        if not url:
                            continue
                        flows += _flows_for(http.get(url).content, direction, period)
                    if not flows:
                        errors.append(f"{period}: sin flujos")
                        continue
                    compute_and_persist(db, period=period, flows=flows)
                    ingested.append(period)
                except Exception as e:  # noqa: BLE001 — per-quarter best-effort
                    db.rollback()  # a bad quarter must not abort the rest of the backfill
                    errors.append(f"{period}: {e}")
    except Exception as e:  # noqa: BLE001 — report, don't crash the op
        logger.warning("DGA trade sync falló: %s", e)
        return {"error": str(e), "periods": [], "errors": [str(e)]}

    return {
        "periods_ingested": len(ingested),
        "periods": ingested,
        "latest": ingested[-1] if ingested else None,
        "errors": errors,
    }
