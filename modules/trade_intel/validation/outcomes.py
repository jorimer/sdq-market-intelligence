"""Realized-shock outcomes for the trade-resilience backtest.

Two outcomes per (country, year), each looking 1–2 years forward and dropping
rows with no lookahead (never fabricated):

PRIMARY — export collapse (the construct the index targets). Realized export
earnings fell ≥ 10% YoY. Same Comtrade source as the index but NOT circular: the
index reads trade STRUCTURE at T (export concentration + import dependency); this
outcome is a future LEVEL shock.

SECONDARY — external shock (CONTRAST, independent of the index inputs). An
external-sector crisis from WDI:
  • current account / GDP deteriorated ≥ 3 pp, OR
  • reserves (months of imports) fell ≥ 1.5 months, OR
  • a recession (real GDP growth < 0) occurred.
The panel shows the index does NOT discriminate it (broad macro distress is
dominated by common global shocks), so it's reported as an honest null contrast.
"""
from typing import Dict, List, Optional

CA_DROP_PP = 3.0          # pp of GDP — current-account deterioration
RES_DROP_MONTHS = 1.5     # months of imports — reserves drawdown
EXPORT_DROP_PCT = 10.0    # % YoY — export-earnings collapse


def _yv(series_iso: Dict[str, float], year: int) -> Optional[float]:
    """Value for an int *year* in a {year_str: value} map."""
    v = series_iso.get(str(year))
    return None if v is None else float(v)


def _growth(levels: Dict[str, float], year: int) -> Optional[float]:
    a, b = _yv(levels, year - 1), _yv(levels, year)
    if a is None or b is None or a <= 0:
        return None
    return (b / a - 1.0) * 100.0


def _external_shock(iso: str, year: int, ca: Dict, res: Dict, gdp: Dict) -> Optional[int]:
    """1 if an external shock hit in year+1/+2, 0 if not, None if no lookahead."""
    c, r, lv = ca.get(iso, {}), res.get(iso, {}), gdp.get(iso, {})
    signals: List[bool] = []
    have = False

    base_ca = _yv(c, year)
    base_res = _yv(r, year)
    for k in (1, 2):
        if base_ca is not None and _yv(c, year + k) is not None:
            have = True
            signals.append(_yv(c, year + k) - base_ca <= -CA_DROP_PP)
        if base_res is not None and _yv(r, year + k) is not None:
            have = True
            signals.append(_yv(r, year + k) - base_res <= -RES_DROP_MONTHS)
        g = _growth(lv, year + k)
        if g is not None:
            have = True
            signals.append(g < 0)

    if not have:
        return None
    return 1 if any(signals) else 0


def _export_collapse(iso: str, year: int, exports: Dict[str, Dict[int, float]]) -> Optional[int]:
    """1 if export earnings fell ≥ EXPORT_DROP_PCT YoY in year+1/+2."""
    e = exports.get(iso, {})
    base = e.get(year)
    if base is None or base <= 0:
        return None
    fwd = [e.get(year + k) for k in (1, 2)]
    fwd = [v for v in fwd if v is not None]
    if not fwd:
        return None
    return 1 if any((v / base - 1.0) * 100.0 <= -EXPORT_DROP_PCT for v in fwd) else 0


def label_panel_external(panel: List[Dict], wdi: Dict[str, Dict]) -> List[Dict]:
    """Attach the external-shock label per panel row (PRIMARY, independent outcome)."""
    ca = wdi.get("current_account_gdp", {})
    res = wdi.get("reserves_import_months", {})
    gdp = wdi.get("gdp_level", {})
    out: List[Dict] = []
    for row in panel:
        lab = _external_shock(row["iso"], row["year"], ca, res, gdp)
        if lab is None:
            continue
        out.append({**row, "label": lab})
    return out


def label_panel_export(panel: List[Dict], exports: Dict[str, Dict[int, float]]) -> List[Dict]:
    """Attach the export-collapse label per panel row (SECONDARY, contrast outcome)."""
    out: List[Dict] = []
    for row in panel:
        lab = _export_collapse(row["iso"], row["year"], exports)
        if lab is None:
            continue
        out.append({**row, "label": lab})
    return out
