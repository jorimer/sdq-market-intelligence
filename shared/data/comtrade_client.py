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


_PARTNER_REF_URL = "https://comtradeapi.un.org/files/v1/app/reference/partnerAreas.json"
# Non-country partner codes to drop: World(0) + aggregates/special categories that
# Comtrade doesn't flag as isGroup (837 Bunkers, 838 Free Zones, 839 Special, 899
# Areas nes, 490 "Other Asia, nes", 568 "Other Europe, nes", 636/637 nes).
_PARTNER_DROP = {0, 490, 568, 636, 637, 837, 838, 839, 899}


def _partner_names() -> Dict[int, str]:
    """{m49_code: country_name} for real countries (drops groups/aggregates)."""
    data = httpx.get(_PARTNER_REF_URL, timeout=40, headers={"User-Agent": "sdq-mip/1.0"}).json()
    out: Dict[int, str] = {}
    for r in data.get("results", []):
        code = r.get("PartnerCode")
        if code in _PARTNER_DROP or r.get("isGroup"):
            continue
        name = (r.get("PartnerDesc") or r.get("text") or "").strip()
        if code is not None and name:
            out[int(code)] = name
    return out


def fetch_trade_partners(m49: str, years: List[int],
                         progress=None) -> Dict[str, Dict[str, Dict[str, float]]]:
    """Bilateral trade by PARTNER country (the geographic dimension the DGA Power BI
    doesn't export): ``{year: {"export": {country: usd_millions}, "import": {...}}}``.

    Omitting partnerCode returns every partner (by M49 code); names are resolved from
    the Comtrade reference. World/aggregate codes are dropped — only real countries."""
    names = _partner_names()
    out: Dict[str, Dict[str, Dict[str, float]]] = {}
    for year in years:
        if progress:
            progress(f"socios {year}")
        year_out: Dict[str, Dict[str, float]] = {}
        for flow, key in (("X", "export"), ("M", "import")):
            rows = _comtrade_get({
                "reporterCode": m49, "period": str(year), "partner2Code": "0",
                "motCode": "0", "customsCode": "C00", "flowCode": flow, "cmdCode": "TOTAL",
            })
            byc: Dict[str, float] = {}
            for r in rows:
                code, val = r.get("partnerCode"), r.get("primaryValue")
                if code in _PARTNER_DROP or val is None:
                    continue
                name = names.get(int(code))
                if name:
                    byc[name] = byc.get(name, 0.0) + float(val) / _USD_TO_MILLIONS
            year_out[key] = {c: round(v, 4) for c, v in byc.items()}
            time.sleep(1.0)
        if year_out.get("export") or year_out.get("import"):
            out[str(year)] = year_out
    return out


def load_partners() -> Dict:
    """Read the committed partner fixture: ``{meta, partners}`` (or ``{}``)."""
    path = _FIXTURES_DIR / "comtrade_partners.json"
    if not path.exists():
        logger.warning("Fixture de socios COMTRADE ausente: %s", path.name)
        return {}
    with path.open(encoding="utf-8") as fh:
        return json.load(fh)


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


def fetch_partner_chapters(m49: str, partner_m49: str, years: List[int],
                           flow: str = "M",
                           progress=None) -> Dict[str, Dict[str, float]]:
    """Comercio bilateral ABIERTO POR CAPÍTULO HS: ``{year: {chapter: usd_millions}}``.

    **El cruce que faltaba.** El sistema tenía dos mitades que nunca se pedían juntas:
    producto × mundo (``cmdCode=AG2``, ``partnerCode=0``) y socio × total
    (``cmdCode=TOTAL``, sin ``partnerCode``). La intersección —qué bienes vienen de QUÉ
    socio— quedaba fuera, y el motor de research la declaraba como límite del sistema
    cuando era un límite de la consulta: la misma API la responde en una llamada.

    El Excel de la DGA no puede suplirlo: publica capítulo × valor SIN país de origen (por
    eso el socio se resolvió vía Comtrade desde el principio). Así que esta es la única vía
    para la pregunta "¿qué le compramos a China, desglosado?".

    Verificado 2026-08-13: RD←China devuelve 93-94 capítulos por año y el total reconcilia
    con la cifra bilateral que el sistema ya publicaba (USD 5.153 MM en 2023).
    """
    out: Dict[str, Dict[str, float]] = {}
    for year in years:
        if progress:
            progress(f"{partner_m49}×capítulos {year}")
        rows = _comtrade_get({
            "reporterCode": m49, "period": str(year), "partnerCode": partner_m49,
            "partner2Code": "0", "motCode": "0", "customsCode": "C00",
            "flowCode": flow, "cmdCode": "AG2",
        })
        by_chapter: Dict[str, float] = {}
        for r in rows:
            code, val = r.get("cmdCode"), r.get("primaryValue")
            # Solo capítulos de 2 dígitos: la respuesta puede traer agregados (TOTAL, AG…)
            # que sumarían dos veces si se dejaran entrar.
            if val is None or not (isinstance(code, str) and code.isdigit() and len(code) == 2):
                continue
            by_chapter[code] = by_chapter.get(code, 0.0) + float(val) / _USD_TO_MILLIONS
        if by_chapter:
            out[str(year)] = {c: round(v, 4) for c, v in sorted(by_chapter.items())}
        time.sleep(1.0)
    return out


def socios_con_flujo(m49: str, year: int, flow: str = "M") -> List[tuple]:
    """``[(m49_socio, nombre, usd_millones)]`` ordenado de mayor a menor, sólo con flujo > 0.

    Es la lista REAL de contrapartes, derivada del dato en vez de fijada a mano. Se ordena por
    valor a propósito: una ingesta que se corte a la mitad deja adentro lo que más pesa.

    **No existe atajo para el cruce socio × capítulo.** Pedir todos los socios y todos los
    capítulos en una sola llamada (omitir ``partnerCode`` con ``cmdCode=AG2``) devuelve como
    máximo 500 filas SIN ordenar por valor, con filas en cero, y —medido el 2026-08-13—
    **deja fuera a China y a Estados Unidos**: cubre 42% del total con apariencia de estar
    completa. Por eso la ingesta itera socio por socio.
    """
    names = _partner_names()
    rows = _comtrade_get({
        "reporterCode": m49, "period": str(year), "partner2Code": "0", "motCode": "0",
        "customsCode": "C00", "flowCode": flow, "cmdCode": "TOTAL",
    })
    out: List[tuple] = []
    for r in rows:
        code, val = r.get("partnerCode"), r.get("primaryValue")
        if code is None or code in _PARTNER_DROP or val is None or float(val) <= 0:
            continue
        nombre = names.get(int(code))
        if nombre:
            out.append((str(code), nombre, float(val) / _USD_TO_MILLIONS))
    out.sort(key=lambda t: -t[2])
    return out
