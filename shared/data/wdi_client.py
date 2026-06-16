"""World Bank WDI + IMF WEO — live connector for the IRMP macro/external inputs.

Feeds Eje 4's *macro* and *external* dimensions with real data for the regional
peer set, replacing the illustrative fixtures. Two upstreams, one client:

  World Bank WDI (https://api.worldbank.org/v2, public, CC-BY 4.0):
    NY.GDP.MKTP.KD        → gdp_cagr_3y          (3-yr CAGR from constant levels)
    FP.CPI.TOTL.ZG        → inflation_gap        (|inflación − meta declarada|)
    FI.RES.TOTL.MO        → reserves_import_months
    BN.CAB.XOKA.GD.ZS     → current_account_gdp
    BX.KLT.DINV.WD.GD.ZS  → fdi_gdp

  IMF WEO (DataMapper, https://www.imf.org/external/datamapper/api/v1):
    GGXWDG_NGDP           → public_debt_gdp      (deuda bruta gob. general / PIB)
    GGXCNL_NGDP           → fiscal_balance_gdp   (balance fiscal gob. general / PIB)

Direction is left raw here; the IRMP engine inverts risk-increasing variables.
The ``Record`` carries the ISO2 country in ``Record.dimension`` (no country field),
mirroring :mod:`shared.data.wgi_client`. Missing values stay ``None`` — never
interpolated. IMF forecasts are excluded: values are capped at the WDI reference
year (latest year with real GDP data), so no projected year leaks in as data.
"""
import logging
import statistics
from datetime import date
from typing import Dict, List, Optional, Tuple

import httpx

from shared.data.base_client import FixtureBackedClient, Record
from shared.data.lineage import Lineage
from shared.doctrine import load_doctrine_raw

logger = logging.getLogger("sdq.data.wdi")

WDI_BASE_URL = "https://api.worldbank.org/v2"
IMF_BASE_URL = "https://www.imf.org/external/datamapper/api/v1"

# Regional peer set: our ISO2 key → ISO3 (what both APIs expect).
PEER_ISO3: Dict[str, str] = {
    "DO": "DOM", "CR": "CRI", "PA": "PAN", "GT": "GTM", "JM": "JAM",
}
ISO3_TO_ISO2: Dict[str, str] = {v: k for k, v in PEER_ISO3.items()}

# WDI indicators consumed AS-IS: code → IRMP variable + unit.
WDI_DIRECT: Dict[str, Tuple[str, str]] = {
    "FI.RES.TOTL.MO": ("reserves_import_months", "meses de importación"),
    "BN.CAB.XOKA.GD.ZS": ("current_account_gdp", "% del PIB"),
    "BX.KLT.DINV.WD.GD.ZS": ("fdi_gdp", "% del PIB"),
}
# WDI series used to DERIVE a variable.
WDI_GDP_LEVEL = "NY.GDP.MKTP.KD"   # constant-USD GDP level → gdp_cagr_3y
WDI_INFLATION = "FP.CPI.TOTL.ZG"   # CPI inflation % → inflation_gap
WDI_FX = "PA.NUS.FCRF"             # official exchange rate (LCU/USD) → fx_volatility
FX_VOL_YEARS = 7                    # annual FX points → up to 6 YoY changes

# IMF WEO indicators: code → IRMP variable (% of GDP).
IMF_INDICATORS: Dict[str, str] = {
    "GGXWDG_NGDP": "public_debt_gdp",
    "GGXCNL_NGDP": "fiscal_balance_gdp",
}

CAGR_YEARS = 3  # gdp_cagr_3y horizon


class WDIApiError(RuntimeError):
    """A WDI/IMF upstream returned an error or an unparseable shape."""


# ── World Bank WDI ────────────────────────────────────────────────
def fetch_wb_indicator(
    indicator: str, iso3_codes: List[str], mrv: int = 1, timeout: int = 30,
) -> Tuple[List[dict], Optional[str]]:
    """GET one WDI indicator for *iso3_codes*. Returns ``(rows, last_updated)``.

    *mrv* = most-recent-values per country (handles publication lag). Raises
    :class:`WDIApiError` on the API's error shape.
    """
    url = f"{WDI_BASE_URL}/country/{';'.join(iso3_codes)}/indicator/{indicator}"
    resp = httpx.get(url, params={"format": "json", "mrv": mrv, "per_page": 2000}, timeout=timeout)
    resp.raise_for_status()
    data = resp.json()
    if not isinstance(data, list) or len(data) < 2:
        msg = data[0].get("message") if isinstance(data, list) and data and isinstance(data[0], dict) else data
        raise WDIApiError(f"WDI {indicator}: respuesta inválida del Banco Mundial ({msg})")
    meta = data[0] if isinstance(data[0], dict) else {}
    return (data[1] or []), meta.get("lastupdated")


# ── IMF WEO (DataMapper) ──────────────────────────────────────────
def fetch_imf_indicator(indicator: str, timeout: int = 30) -> Dict[str, Dict[str, float]]:
    """GET one IMF WEO indicator. Returns ``{iso3: {year: value}}``.

    The DataMapper ignores country/period filters and returns the full dataset,
    so callers filter client-side. Raises :class:`WDIApiError` on a bad shape.
    """
    resp = httpx.get(f"{IMF_BASE_URL}/{indicator}", timeout=timeout)
    resp.raise_for_status()
    data = resp.json()
    values = data.get("values", {}).get(indicator) if isinstance(data, dict) else None
    if not isinstance(values, dict):
        raise WDIApiError(f"IMF {indicator}: respuesta inválida del FMI")
    return values


def _cagr(level_old: float, level_new: float, years: int) -> Optional[float]:
    """Compound annual growth rate (%) between two levels, or None if undefined."""
    if level_old is None or level_new is None or level_old <= 0 or level_new <= 0:
        return None
    return round(((level_new / level_old) ** (1.0 / years) - 1.0) * 100.0, 2)


def _fx_volatility(fx_by_year: Dict[int, float]) -> Optional[float]:
    """σ of year-over-year %-changes of the exchange rate (annual-based proxy).

    Needs ≥3 yearly points (≥2 changes). A flat (dollarized) series → 0.0.
    Returns None when there isn't enough history — never fabricated.
    """
    years = sorted(y for y, v in fx_by_year.items() if v is not None and v > 0)
    if len(years) < 3:
        return None
    changes = [
        100.0 * (fx_by_year[years[i]] - fx_by_year[years[i - 1]]) / fx_by_year[years[i - 1]]
        for i in range(1, len(years))
    ]
    return round(statistics.pstdev(changes), 2)


def declared_sovereign_records(period: str) -> List[Record]:
    """Emit ``sovereign_rating_score`` from the declared doctrine table.

    Not an API value: S&P long-term FC ratings are maintained in
    ``regulatory.yaml`` (with agency + as-of date) and mapped to 0-100 via the
    declared ``rating_scale``. Stamped at *period* so it aligns with the live
    data in a snapshot. Source ``SDQ_DECLARED`` makes the provenance explicit.
    """
    doc = load_doctrine_raw("regulatory")
    ratings = doc.get("sovereign_ratings", {})
    scale = doc.get("rating_scale", {})
    out: List[Record] = []
    for iso2, info in ratings.items():
        rating = info.get("rating") if isinstance(info, dict) else None
        score = scale.get(rating)
        lineage = Lineage(
            source="SDQ_DECLARED", license="declarado (doctrina)",
            fetched_at=date.today(),
            note=f"rating S&P {rating} ({info.get('as_of') if isinstance(info, dict) else '?'}) → escala declarada",
        )
        out.append(Record(
            series="sovereign_rating_score", period=period,
            value=None if score is None else float(score),
            lineage=lineage, unit="0-100 (escala S&P declarada)", dimension=iso2,
        ))
    return out


class WDIClient(FixtureBackedClient):
    source = "WDI"
    license = "World Bank Open Data (CC-BY 4.0)"
    license_ok = True
    fixture_file = "wdi.json"
    live_phase = "Fase 4 (Eje 4 · macro/externa)"

    def fetch(self, series: Optional[str] = None, period: Optional[str] = None) -> List[Record]:
        self.check_license()
        if self.mode == "live":
            return self._fetch_live(series, period)
        return self._fetch_fixture(series, period)

    # ── Live ──────────────────────────────────────────────────────
    def _fetch_live(self, series: Optional[str], period: Optional[str]) -> List[Record]:  # pragma: no cover - network I/O
        iso3 = list(PEER_ISO3.values())
        out: List[Record] = []
        ref_year: Optional[int] = None

        # 1) gdp_cagr_3y — needs CAGR_YEARS+1 constant-GDP levels per country.
        try:
            rows, published = fetch_wb_indicator(WDI_GDP_LEVEL, iso3, mrv=CAGR_YEARS + 1)
            pub = _parse_date(published)
            by_country: Dict[str, Dict[int, float]] = {}
            for r in rows:
                iso, yr, val = r.get("countryiso3code"), r.get("date"), r.get("value")
                if iso and yr and val is not None:
                    by_country.setdefault(iso, {})[int(yr)] = float(val)
            for iso, levels in by_country.items():
                if not levels:
                    continue
                newest = max(levels)
                ref_year = newest if ref_year is None else max(ref_year, newest)
                cagr = _cagr(levels.get(newest - CAGR_YEARS), levels.get(newest), CAGR_YEARS)
                out.append(self._record(
                    "gdp_cagr_3y", str(newest), cagr, iso,
                    "% (CAGR 3a, PIB real)", WDI_GDP_LEVEL, pub,
                    note=f"CAGR {CAGR_YEARS}a desde niveles de PIB constante",
                ))
        except (WDIApiError, httpx.HTTPError, ValueError) as e:
            logger.warning("[WDI live] %s falló: %s", WDI_GDP_LEVEL, e)

        # 2) inflation_gap — |inflación − meta declarada en doctrina|.
        targets = self._inflation_targets()
        try:
            rows, published = fetch_wb_indicator(WDI_INFLATION, iso3, mrv=1)
            pub = _parse_date(published)
            for r in rows:
                iso2 = ISO3_TO_ISO2.get(r.get("countryiso3code") or "")
                infl, yr = r.get("value"), r.get("date")
                gap = None
                if infl is not None and iso2 in targets:
                    gap = round(abs(float(infl) - targets[iso2]), 2)
                out.append(self._record(
                    "inflation_gap", str(yr) if yr else "", gap, r.get("countryiso3code") or "",
                    "pp (|infl − meta|)", WDI_INFLATION, pub,
                    note="brecha vs meta declarada (doctrina inflation_targets)",
                ))
        except (WDIApiError, httpx.HTTPError, ValueError) as e:
            logger.warning("[WDI live] %s falló: %s", WDI_INFLATION, e)

        # 3) WDI direct variables (value used as-is).
        for code, (var, unit) in WDI_DIRECT.items():
            try:
                rows, published = fetch_wb_indicator(code, iso3, mrv=1)
            except (WDIApiError, httpx.HTTPError, ValueError) as e:
                logger.warning("[WDI live] %s falló: %s", code, e)
                continue
            pub = _parse_date(published)
            for r in rows:
                out.append(self._record(
                    var, str(r.get("date") or ""), r.get("value"),
                    r.get("countryiso3code") or "", unit, code, pub,
                ))

        # 3.5) fx_volatility — annual-based proxy: σ of YoY %-changes of the
        #      official exchange rate over FX_VOL_YEARS. Dollarized PA → ~0.
        try:
            rows, published = fetch_wb_indicator(WDI_FX, iso3, mrv=FX_VOL_YEARS)
            pub = _parse_date(published)
            by_country: Dict[str, Dict[int, float]] = {}
            for r in rows:
                iso, yr, val = r.get("countryiso3code"), r.get("date"), r.get("value")
                if iso and yr and val is not None:
                    by_country.setdefault(iso, {})[int(yr)] = float(val)
            for iso, fx in by_country.items():
                vol = _fx_volatility(fx)
                newest = max(fx) if fx else None
                out.append(self._record(
                    "fx_volatility", str(newest) if newest else "", vol, iso,
                    "σ cambios % anuales (base anual)", WDI_FX, pub,
                    note="proxy de volatilidad cambiaria (base anual, no mensual)",
                ))
        except (WDIApiError, httpx.HTTPError, ValueError) as e:
            logger.warning("[WDI live] %s falló: %s", WDI_FX, e)

        # 4) IMF WEO — debt + fiscal balance, capped at the WDI reference year so
        #    no forecast year leaks in as data. Without a real reference year
        #    (WDI GDP unavailable) we skip IMF entirely rather than risk
        #    persisting a WEO projection as if it were observed data.
        if ref_year is None:
            logger.warning(
                "[IMF live] sin año de referencia WDI; se omite IMF para no arriesgar proyecciones"
            )
        else:
            for code, var in IMF_INDICATORS.items():
                try:
                    values = fetch_imf_indicator(code)
                except (WDIApiError, httpx.HTTPError, ValueError) as e:
                    logger.warning("[IMF live] %s falló: %s", code, e)
                    continue
                for iso2, iso3c in PEER_ISO3.items():
                    obs = values.get(iso3c, {})
                    year = _latest_year_at_or_before(obs, ref_year)
                    val = obs.get(str(year)) if year else None
                    out.append(self._record(
                        var, str(year) if year else "", val, iso3c,
                        "% del PIB", code, None, source="IMF_WEO",
                        note="WEO; capado al año de referencia WDI (sin proyecciones)",
                    ))
        return _filter(out, series, period)

    def _record(
        self, var: str, period: str, value, iso3: str, unit: str, code: str,
        published: Optional[date], *, source: Optional[str] = None, note: str = "",
    ) -> Record:
        src = source or self.source
        base = WDI_BASE_URL if src == "WDI" else IMF_BASE_URL
        lineage = Lineage(
            source=src, license=self.license if src == "WDI" else "IMF WEO (terms of use)",
            published_at=published, fetched_at=date.today(),
            url=f"{base}/{code}", note=note,
        )
        return Record(
            series=var, period=period,
            value=None if value is None else float(value),
            lineage=lineage, unit=unit,
            dimension=ISO3_TO_ISO2.get(iso3, iso3),  # country carried here
        )

    def _inflation_targets(self) -> Dict[str, float]:
        raw = load_doctrine_raw("regulatory").get("inflation_targets", {})
        return {k: float(v) for k, v in raw.items()}

    # ── Fixture (offline / tests) ─────────────────────────────────
    def _fetch_fixture(self, series: Optional[str], period: Optional[str]) -> List[Record]:
        """Fixture shape: ``{"<iso2>": {"<var>": {"<year>": value}}}``."""
        fixture = self._load_fixture(self.fixture_file)
        lineage = Lineage(source=self.source, license=self.license, fetched_at=date.today())
        out: List[Record] = []
        for iso2, vars_ in fixture.items():
            for var, obs in vars_.items():
                for yr, val in obs.items():
                    out.append(Record(
                        series=var, period=str(yr),
                        value=None if val is None else float(val),
                        lineage=lineage, unit=None, dimension=iso2,
                    ))
        return _filter(out, series, period)


def _latest_year_at_or_before(obs: Dict[str, float], cap: int) -> Optional[int]:
    """Most recent year in *obs* that is ≤ *cap* and has a value."""
    years = [int(y) for y, v in obs.items() if v is not None and y.isdigit() and int(y) <= cap]
    return max(years) if years else None


def _filter(records: List[Record], series: Optional[str], period: Optional[str]) -> List[Record]:
    if series:
        records = [r for r in records if r.series == series]
    if period:
        records = [r for r in records if r.period == period]
    return records


def _parse_date(s: Optional[str]) -> Optional[date]:
    if not s:
        return None
    try:
        return date.fromisoformat(s[:10])
    except ValueError:
        return None


wdi_client = WDIClient()
