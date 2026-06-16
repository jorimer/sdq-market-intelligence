"""Historical IRMP panel for the Eje-4 backtest.

Reconstructs the IRMP for the peer set over past years from the annual-history
core: WDI macro + WGI governance + IMF debt/fiscal + FX volatility. GDELT events
and the sovereign rating have no usable annual history, so the events dimension
and the judgment vars are held at their STATIC declared rubric values (constant
across years, NOT sourced) — only the macro/governance/external core varies over
time. So the backtest validates the IRMP's time-varying core, and the score never
moves with the live GDELT signal (which matters: the backtest's instability
outcome is a GDELT signal, so this keeps them independent). Each year's IRMP is
normalized within that year's peer set.
"""
import logging
from typing import Dict, List, Optional

import httpx

from modules.macro_political_risk.scoring.engine import run_irmp
from shared.data.wdi_client import ISO3_TO_ISO2, PEER_ISO3, _cagr, _fx_volatility
from shared.data.wgi_client import WGI_INDICATORS
from shared.doctrine import load_doctrine_raw

logger = logging.getLogger("sdq.mpr.validation.historical")

WB_URL = "https://api.worldbank.org/v2"
IMF_URL = "https://www.imf.org/external/datamapper/api/v1"

# WDI series → IRMP variable (direct, taken at year Y).
WDI_DIRECT = {
    "FI.RES.TOTL.MO": "reserves_import_months",
    "BN.CAB.XOKA.GD.ZS": "current_account_gdp",
    "BX.KLT.DINV.WD.GD.ZS": "fdi_gdp",
}
WDI_GDP_LEVEL = "NY.GDP.MKTP.KD"
WDI_INFLATION = "FP.CPI.TOTL.ZG"
WDI_FX = "PA.NUS.FCRF"
IMF_INDICATORS = {"GGXWDG_NGDP": "public_debt_gdp", "GGXCNL_NGDP": "fiscal_balance_gdp"}

# yearly series: {var_or_code: {iso2: {year:int -> value}}}
Series = Dict[str, Dict[str, Dict[int, float]]]


def _wb_series(code: str, mrv: int, timeout: int = 45) -> Dict[str, Dict[int, float]]:
    iso3 = ";".join(PEER_ISO3.values())
    resp = httpx.get(f"{WB_URL}/country/{iso3}/indicator/{code}",
                     params={"format": "json", "mrv": mrv, "per_page": 4000}, timeout=timeout)
    resp.raise_for_status()
    data = resp.json()
    out: Dict[str, Dict[int, float]] = {}
    for row in (data[1] if isinstance(data, list) and len(data) > 1 and data[1] else []):
        iso2 = ISO3_TO_ISO2.get(row.get("countryiso3code"))
        if iso2 and row.get("value") is not None and str(row.get("date", "")).isdigit():
            out.setdefault(iso2, {})[int(row["date"])] = float(row["value"])
    return out


def _imf_series(code: str, timeout: int = 45) -> Dict[str, Dict[int, float]]:
    resp = httpx.get(f"{IMF_URL}/{code}", timeout=timeout)
    resp.raise_for_status()
    vals = resp.json().get("values", {}).get(code, {})
    out: Dict[str, Dict[int, float]] = {}
    for iso2, iso3 in PEER_ISO3.items():
        obs = vals.get(iso3, {})
        out[iso2] = {int(y): float(v) for y, v in obs.items() if v is not None and y.isdigit()}
    return out


def fetch_series(mrv: int = 14) -> Series:  # pragma: no cover - network I/O
    """Fetch every historical series needed to rebuild the IRMP core."""
    series: Series = {}
    series[WDI_GDP_LEVEL] = _wb_series(WDI_GDP_LEVEL, mrv)
    series[WDI_INFLATION] = _wb_series(WDI_INFLATION, mrv)
    series[WDI_FX] = _wb_series(WDI_FX, mrv)
    for code in WDI_DIRECT:
        series[code] = _wb_series(code, mrv)
    for code, var in WGI_INDICATORS.items():
        series[var] = _wb_series(code, mrv)   # WGI codes via the same WB API
    for code, var in IMF_INDICATORS.items():
        series[var] = _imf_series(code)
    return series


def _dataset_for_year(series: Series, year: int, targets: Dict[str, float],
                      rubric: Dict[str, Dict[str, float]]) -> Dict[str, Dict[str, float]]:
    """Assemble ``{iso: {var: value}}`` for *year* from the fetched series."""
    dataset: Dict[str, Dict[str, float]] = {}
    for iso2 in PEER_ISO3:
        row: Dict[str, float] = {}
        # gdp_cagr_3y from constant-GDP levels Y-3..Y
        lv = series.get(WDI_GDP_LEVEL, {}).get(iso2, {})
        cagr = _cagr(lv.get(year - 3), lv.get(year), 3)
        if cagr is not None:
            row["gdp_cagr_3y"] = cagr
        # inflation_gap
        infl = series.get(WDI_INFLATION, {}).get(iso2, {}).get(year)
        if infl is not None and iso2 in targets:
            row["inflation_gap"] = round(abs(infl - targets[iso2]), 2)
        # fx_volatility over [Y-6, Y]
        fx = {y: v for y, v in series.get(WDI_FX, {}).get(iso2, {}).items() if year - 6 <= y <= year}
        vol = _fx_volatility(fx)
        if vol is not None:
            row["fx_volatility"] = vol
        # direct WDI + IMF + WGI at Y
        for code, var in WDI_DIRECT.items():
            v = series.get(code, {}).get(iso2, {}).get(year)
            if v is not None:
                row[var] = v
        for var in list(WGI_INDICATORS.values()) + list(IMF_INDICATORS.values()):
            v = series.get(var, {}).get(iso2, {}).get(year)
            if v is not None:
                row[var] = v
        # declared rubric judgment vars (static)
        for var, val in (rubric.get(iso2) or {}).items():
            row.setdefault(var, float(val))
        dataset[iso2] = row
    return dataset


MIN_YEAR = 2010   # WGI is annual and well-covered from here


def build_panel(series: Optional[Series] = None, mrv: int = 14) -> List[Dict]:
    """IRMP panel: one row per (country, year) with the reconstructed core score.

    Returns ``[{iso, year, irmp_score, risk_band}]`` for realized years (≥2010,
    capped at the latest WDI actual so IMF forecast years never enter) where the
    real core (GDP CAGR + WGI) is present for the FULL peer set, so the regional
    normalization is meaningful.
    """
    if series is None:  # pragma: no cover - network I/O
        series = fetch_series(mrv)
    doc = load_doctrine_raw("regulatory")
    targets = {k: float(v) for k, v in doc.get("inflation_targets", {}).items()}
    rubric = doc.get("rubric_inputs", {})

    # WDI has no forecasts → its latest year is the realized cap (excludes WEO projections).
    realized_max = max(
        (y for c in series.get("FI.RES.TOTL.MO", {}).values() for y in c), default=MIN_YEAR
    )
    years = [y for y in sorted({y for s in series.values() for c in s.values() for y in c})
             if MIN_YEAR <= y <= realized_max]
    panel: List[Dict] = []
    for year in years:
        dataset = _dataset_for_year(series, year, targets, rubric)
        # require the real time-varying core for ALL peers (drops sparse years)
        if any("gdp_cagr_3y" not in dataset[iso] or "wgi_rule_of_law" not in dataset[iso]
               for iso in PEER_ISO3):
            continue
        for iso2 in PEER_ISO3:
            try:
                res = run_irmp(iso2, dataset)
            except (KeyError, ZeroDivisionError):
                continue
            panel.append({"iso": iso2, "year": year,
                          "irmp_score": res["irmp_score"], "risk_band": res["risk_band"]})
    return panel
