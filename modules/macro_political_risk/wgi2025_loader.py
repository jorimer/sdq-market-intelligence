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
import statistics
from pathlib import Path
from typing import Callable, Dict, List, Optional

from sqlalchemy.orm import Session

from modules.macro_political_risk.models.models import CountryVariable

logger = logging.getLogger("sdq.mpr.wgi2025")

_ASSET_PATH = Path(__file__).resolve().parent / "data" / "wgi2025.json"

SOURCE_TAG = "WGI-2025"
SOURCE_TAG_DERIVED = "WGI-2025 (derivado)"

# `regulatory_volatility_5y` (IRMP, regulación · risk-increasing) se DERIVA de la
# serie WGI de calidad regulatoria en vez de teclearse: la desviación estándar de las
# últimas ``_REG_VOL_WINDOW`` observaciones anuales = inestabilidad regulatoria real.
# Es una señal DISTINTA del nivel (``wgi_regulatory_quality``, que ya es input aparte),
# así que no hay doble conteo. El motor del IRMP la normaliza min-max contra el peer set
# y la invierte (más volatilidad → más riesgo). Espeja ``_load_wgi_volatility`` del IAI.
_REG_VOL_VAR = "regulatory_volatility_5y"
_REG_VOL_SOURCE_DIM = "wgi_regulatory_quality"
_REG_VOL_WINDOW = 5

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


def _regulatory_volatility(by_year: Dict[str, dict]) -> Optional[tuple]:
    """``(period, std, n)`` for the regulatory-quality volatility of one country:
    population std of the last ``_REG_VOL_WINDOW`` annual scores. ``None`` when
    there are <2 usable points (no variance computable)."""
    pts: List[tuple] = [
        (yr, e["score"]) for yr, e in by_year.items() if e.get("score") is not None
    ]
    if len(pts) < 2:
        return None
    pts.sort(key=lambda p: int(p[0]))
    window = pts[-_REG_VOL_WINDOW:]
    scores = [s for _yr, s in window]
    return window[-1][0], round(statistics.pstdev(scores), 4), len(window)


def ingest_wgi2025(
    db: Session,
    asset: Optional[dict] = None,
    set_phase: Optional[Callable[[str], None]] = None,
) -> Dict:
    """Upsert every (country, year, variable) governance observation from the
    asset. Idempotent by the ``(iso_code, period, variable)`` unique key. Also
    derives and persists ``regulatory_volatility_5y`` per country (std of the
    regulatory-quality series) so the IRMP scores it as real, not rubric.

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
    # Derived regulatory_volatility_5y rows are keyed outside the wgi_% space, so
    # prefetch them separately to stay idempotent across re-runs.
    existing_vol = {
        (r.iso_code, r.variable): r
        for r in db.query(CountryVariable).filter(
            CountryVariable.variable == _REG_VOL_VAR
        )
    }

    upserts, years, errors, derived = 0, set(), [], 0
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
        # Derivar la volatilidad regulatoria (una fila por país, al período más
        # reciente de la serie). Mata la rúbrica `regulatory_volatility_5y` del IRMP.
        vol = _regulatory_volatility(by_var.get(_REG_VOL_SOURCE_DIM, {}))
        if vol is not None:
            vperiod, vstd, vn = vol
            vmeta = {"derived_from": _REG_VOL_SOURCE_DIM, "window": _REG_VOL_WINDOW, "n": vn}
            vrow = existing_vol.get((iso2, _REG_VOL_VAR))
            if vrow is None:
                vrow = CountryVariable(
                    iso_code=iso2, period=vperiod, variable=_REG_VOL_VAR,
                    value=vstd, source=SOURCE_TAG_DERIVED, meta=vmeta,
                )
                db.add(vrow)
                existing_vol[(iso2, _REG_VOL_VAR)] = vrow
            else:
                vrow.period, vrow.value = vperiod, vstd
                vrow.source, vrow.meta = SOURCE_TAG_DERIVED, vmeta
            derived += 1
        set_phase(f"cargando {iso3}")

    db.commit()
    logger.info("WGI-2025 ingest: %d upserts, %d economías, años %s-%s",
                upserts, len(data), min(years) if years else "-",
                max(years) if years else "-")
    return {
        "upserts": upserts,
        "derived_regulatory_volatility": derived,
        "economies": len(data),
        "years": sorted(years),
        "source": SOURCE_TAG,
        "errors": errors,
    }
