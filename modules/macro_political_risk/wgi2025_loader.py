"""WGI-2025 loader — ingest the canonical governance asset into the IRMP store.

Reads ``data/wgi2025.json`` (built from the World Bank's December 2025
reproducibility file by ``scripts/build_wgi2025_asset.py``) and upserts one
``CountryVariable`` per (country, year, governance variable). The scalar
``value`` is the absolute 0-100 score; the ``meta`` JSON carries the standard
error, 90% confidence interval, source count and 35-source breakdown.

This SUPERSEDES the live ``wgi_sync`` (API, ``mrv=1``, single year, old relative
percentile) for the six ``wgi_*`` variables: it brings the full 1996-2024
recalculated series on the absolute scale plus the uncertainty and source
metadata the product needs for trajectory, confidence and drill-down.
"""
import json
import logging
from pathlib import Path
from typing import Callable, Dict, Optional

from sqlalchemy.orm import Session

from modules.macro_political_risk.models.models import CountryVariable

logger = logging.getLogger("sdq.mpr.wgi2025")

_ASSET_PATH = Path(__file__).resolve().parent / "data" / "wgi2025.json"

SOURCE_TAG = "WGI-2025"

# iso3 (asset keys) → iso2 (CountryVariable.iso_code). Mirrors validation/peers.py.
ISO3_TO_ISO2: Dict[str, str] = {
    "DOM": "DO", "CRI": "CR", "PAN": "PA", "GTM": "GT", "JAM": "JM",
    "ARG": "AR", "BOL": "BO", "BRA": "BR", "CHL": "CL", "COL": "CO",
    "ECU": "EC", "SLV": "SV", "HND": "HN", "MEX": "MX", "NIC": "NI",
    "PRY": "PY", "PER": "PE", "TTO": "TT", "URY": "UY", "VEN": "VE",
    "BLZ": "BZ", "HTI": "HT", "GUY": "GY", "SUR": "SR",
}


def load_asset(path: Optional[Path] = None) -> dict:
    """Read the canonical WGI-2025 JSON asset. Raises if missing/corrupt."""
    p = path or _ASSET_PATH
    with open(p, "r", encoding="utf-8") as fh:
        return json.load(fh)


def ingest_wgi2025(
    db: Session,
    asset: Optional[dict] = None,
    set_phase: Optional[Callable[[str], None]] = None,
) -> Dict:
    """Upsert every (country, year, variable) governance observation from the
    asset. Idempotent by the ``(iso_code, period, variable)`` unique key.

    Returns a summary: rows upserted, economies, years covered, errors[].
    """
    set_phase = set_phase or (lambda _m: None)
    asset = asset or load_asset()
    data = asset.get("data", {})

    set_phase("indexando filas existentes")
    # One query for the whole WGI variable space, then match in memory — avoids a
    # per-row SELECT (24 countries × 6 vars × 26 years ≈ 3.7k rows).
    existing = {
        (r.iso_code, r.period, r.variable): r
        for r in db.query(CountryVariable).filter(
            CountryVariable.variable.like("wgi_%")
        )
    }

    upserts, years, errors = 0, set(), []
    for iso3, by_var in data.items():
        iso2 = ISO3_TO_ISO2.get(iso3)
        if not iso2:
            errors.append(f"iso3 sin mapeo a iso2: {iso3}")
            continue
        for var, by_year in by_var.items():
            for year, entry in by_year.items():
                score = entry.get("score")
                if score is None:
                    continue
                years.add(year)
                meta = {
                    "se": entry.get("se"),
                    "ci_lo": entry.get("ci_lo"),
                    "ci_hi": entry.get("ci_hi"),
                    "n_sources": entry.get("n_sources"),
                    "sources": entry.get("sources") or {},
                }
                row = existing.get((iso2, year, var))
                if row is None:
                    row = CountryVariable(
                        iso_code=iso2, period=year, variable=var,
                        value=score, source=SOURCE_TAG, meta=meta,
                    )
                    db.add(row)
                    existing[(iso2, year, var)] = row
                else:
                    row.value = score
                    row.source = SOURCE_TAG
                    row.meta = meta
                upserts += 1
        set_phase(f"cargando {iso3}")

    db.commit()
    logger.info("WGI-2025 ingest: %d upserts, %d economías, años %s-%s",
                upserts, len(data), min(years) if years else "-",
                max(years) if years else "-")
    return {
        "upserts": upserts,
        "economies": len(data),
        "years": sorted(years),
        "source": SOURCE_TAG,
        "errors": errors,
    }
