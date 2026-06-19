"""UN Comtrade connector — real merchandise-trade flows for the resilience panel.

Free public data (UN Comtrade), no key required for the preview endpoint. For the
Gate-E trade-resilience backtest we need, per country and year:
  * exports by HS-2 chapter  → HHI / diversification (the scorer is share-based),
  * total imports            → import dependency.

We also pull the WDI external-sector outcomes (current account, reserves) and the
GDP level (for the recession check) over the same panel, from the World Bank API,
so the whole backtest dataset comes from two public, attribution-only sources.

Built once into ``fixtures/comtrade_panel.json`` (trade history is static), with a
``live`` path kept real and runnable so the fixture is just its cached output —
the mixed-source pattern used across the data layer. Missing values stay absent;
nothing is interpolated or fabricated. A wrong reporter code yields an empty pull
→ that country is simply dropped (and surfaced in the coverage block).
"""
import json
import logging
import time
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import httpx

logger = logging.getLogger("sdq.data.comtrade")

_FIXTURES_DIR = Path(__file__).resolve().parent / "fixtures"
FIXTURE_FILE = "comtrade_panel.json"

COMTRADE_URL = "https://comtradeapi.un.org/public/v1/preview/C/A/HS"
WB_URL = "https://api.worldbank.org/v2"

SOURCE = "UN Comtrade + World Bank WDI"
LICENSE = "UN Comtrade & World Bank Open Data (free, attribution)"

_USD_TO_MILLIONS = 1_000_000.0

# WDI outcome series → friendly name. External-sector channel + GDP level.
WDI_CURRENT_ACCOUNT = "BN.CAB.XOKA.GD.ZS"     # current account balance, % of GDP
WDI_RESERVES_MONTHS = "FI.RES.TOTL.MO"        # reserves in months of imports
WDI_GDP_LEVEL = "NY.GDP.MKTP.KD"              # constant-USD GDP level → growth
WDI_SERIES = {
    WDI_CURRENT_ACCOUNT: "current_account_gdp",
    WDI_RESERVES_MONTHS: "reserves_import_months",
    WDI_GDP_LEVEL: "gdp_level",
}


# ── Fixture load (default mode) ───────────────────────────────────────────
def load_panel() -> Dict:
    """Read the committed panel fixture: ``{meta, trade, wdi}`` (or ``{}``)."""
    path = _FIXTURES_DIR / FIXTURE_FILE
    if not path.exists():
        logger.warning("Fixture COMTRADE ausente: %s", path.name)
        return {}
    with path.open(encoding="utf-8") as fh:
        return json.load(fh)


# ── Live fetch ────────────────────────────────────────────────────────────
def _chunks(years: List[int], size: int) -> List[List[int]]:
    return [years[i:i + size] for i in range(0, len(years), size)]


def _comtrade_get(params: Dict[str, str], timeout: int = 60,
                  retries: int = 5) -> List[Dict]:
    """GET with backoff on 429 (the anonymous preview has a short-window quota).

    The window recovers within a minute, so exponential backoff clears it without
    needing an API key.
    """
    backoff = 20.0
    for attempt in range(retries):
        resp = httpx.get(COMTRADE_URL, params=params, timeout=timeout,
                         headers={"User-Agent": "sdq-mip/1.0"})
        if resp.status_code == 429 and attempt < retries - 1:
            logger.info("COMTRADE 429 — backoff %.0fs (intento %d)", backoff, attempt + 1)
            time.sleep(backoff)
            backoff *= 2
            continue
        resp.raise_for_status()
        return resp.json().get("data", []) or []
    return []


def fetch_exports_by_chapter(m49: str, years: List[int]) -> Dict[str, Dict[str, float]]:
    """``{year: {hs2_chapter: export_value_usd_millions}}`` for one reporter.

    Pulled in ≤4-year groups so each preview call stays under the 500-row cap
    (99 chapters × 4 years < 500). Values aggregated by chapter (USD millions).
    """
    out: Dict[str, Dict[str, float]] = {}
    for grp in _chunks(years, 4):
        rows = _comtrade_get({
            "reporterCode": m49, "period": ",".join(str(y) for y in grp),
            "partnerCode": "0", "partner2Code": "0", "motCode": "0",
            "customsCode": "C00", "flowCode": "X", "cmdCode": "AG2",
        })
        for r in rows:
            chap, period = r.get("cmdCode"), str(r.get("period"))
            val = r.get("primaryValue")
            if not chap or val is None:
                continue
            out.setdefault(period, {})
            out[period][chap] = out[period].get(chap, 0.0) + float(val) / _USD_TO_MILLIONS
        time.sleep(2.0)  # be gentle on the unauthenticated endpoint
    return {y: {c: round(v, 4) for c, v in ch.items()} for y, ch in out.items()}


def fetch_imports_total(m49: str, years: List[int]) -> Dict[str, float]:
    """``{year: total_imports_usd_millions}`` for one reporter (cmdCode=TOTAL).

    Chunked into ≤8-year groups: the preview rejects long period lists (400).
    """
    out: Dict[str, float] = {}
    for grp in _chunks(years, 8):
        rows = _comtrade_get({
            "reporterCode": m49, "period": ",".join(str(y) for y in grp),
            "partnerCode": "0", "partner2Code": "0", "motCode": "0",
            "customsCode": "C00", "flowCode": "M", "cmdCode": "TOTAL",
        })
        for r in rows:
            val = r.get("primaryValue")
            if val is not None:
                out[str(r.get("period"))] = round(float(val) / _USD_TO_MILLIONS, 4)
        time.sleep(2.0)
    return out


def fetch_country_trade(m49: str, years: List[int]) -> Dict[str, Dict]:
    """``{year: {exports_by_chapter, imports_total}}`` for one reporter.

    Exports and imports are fetched independently so a one-sided failure still
    keeps the other side (the scorer needs both for a year to be usable, but the
    builder is resumable and surfaces gaps rather than discarding the country).
    """
    exports = fetch_exports_by_chapter(m49, years)
    imports = fetch_imports_total(m49, years)
    country: Dict[str, Dict] = {}
    for y in years:
        ys = str(y)
        ex, im = exports.get(ys), imports.get(ys)
        if not ex and im is None:
            continue
        country[ys] = {"exports_by_chapter": ex or {}, "imports_total": im}
    return country


def fetch_trade(peers: Dict[str, Dict[str, str]], years: List[int],
                progress=None) -> Dict[str, Dict[str, Dict]]:
    """Per-country trade matrix: ``{iso2: {year: {exports_by_chapter, imports_total}}}``."""
    trade: Dict[str, Dict[str, Dict]] = {}
    for iso2, info in peers.items():
        if progress:
            progress(f"comercio {iso2}")
        try:
            country = fetch_country_trade(info["m49"], years)
        except httpx.HTTPError as e:
            logger.warning("COMTRADE %s falló: %s", iso2, e)
            continue
        if country:
            trade[iso2] = country
    return trade


def _wb_series(code: str, iso3_to_iso2: Dict[str, str], mrv: int,
               timeout: int = 60) -> Dict[str, Dict[str, float]]:
    """``{iso2: {year_str: value}}`` for a World Bank indicator over the panel."""
    iso3 = ";".join(iso3_to_iso2.keys())
    resp = httpx.get(f"{WB_URL}/country/{iso3}/indicator/{code}",
                     params={"format": "json", "mrv": mrv, "per_page": 20000},
                     timeout=timeout)
    resp.raise_for_status()
    data = resp.json()
    out: Dict[str, Dict[str, float]] = {}
    for row in (data[1] if isinstance(data, list) and len(data) > 1 and data[1] else []):
        iso2 = iso3_to_iso2.get(row.get("countryiso3code"))
        if iso2 and row.get("value") is not None and str(row.get("date", "")).isdigit():
            out.setdefault(iso2, {})[str(row["date"])] = float(row["value"])
    return out


def fetch_wdi(peers: Dict[str, Dict[str, str]], mrv: int = 18) -> Dict[str, Dict[str, Dict[str, float]]]:
    """External-sector outcomes + GDP level over the panel, keyed by friendly name."""
    iso3_to_iso2 = {v["iso3"]: k for k, v in peers.items()}
    return {name: _wb_series(code, iso3_to_iso2, mrv) for code, name in WDI_SERIES.items()}


def build_panel_dataset(peers: Dict[str, Dict[str, str]], years: List[int],
                        progress=None) -> Dict:
    """Assemble the full backtest dataset (trade + WDI) — the live path; its output
    is what the fixture caches."""
    if progress:
        progress("descargando comercio (UN Comtrade)")
    trade = fetch_trade(peers, years, progress=progress)
    if progress:
        progress("descargando outcomes externos (World Bank WDI)")
    wdi = fetch_wdi(peers)
    return {
        "meta": {
            "source": SOURCE, "license": LICENSE,
            "years": [years[0], years[-1]], "n_peers": len(peers),
            "countries_with_trade": sorted(trade.keys()),
        },
        "trade": trade,
        "wdi": wdi,
    }
