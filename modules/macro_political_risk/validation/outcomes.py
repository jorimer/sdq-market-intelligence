"""Sovereign-distress outcomes for the IRMP backtest.

For each (country, year) we label whether sovereign distress materialized in the
following two years, from the same WDI/IMF annual series used to build the panel:

  • public debt/GDP rose ≥ 7 pp, OR
  • a recession (real GDP growth < 0) occurred, OR
  • the fiscal balance worsened ≥ 3 pp of GDP.

HONESTY: these macro-fiscal outcomes overlap with index inputs (debt, growth,
fiscal are IRMP variables), so this measures whether the composite anticipates
deterioration — not a fully independent event. An independent agency-downgrade
label would be cleaner but isn't freely sourceable per year. Stated in the report.
"""
from typing import Dict, List, Optional

from modules.macro_political_risk.validation.historical import WDI_GDP_LEVEL

DEBT_JUMP_PP = 7.0
FISCAL_DROP_PP = 3.0


def _growth(levels: Dict[int, float], year: int) -> Optional[float]:
    a, b = levels.get(year - 1), levels.get(year)
    if a is None or b is None or a <= 0:
        return None
    return (b / a - 1.0) * 100.0


def _distress(iso: str, year: int, debt: Dict, fiscal: Dict, levels: Dict) -> Optional[int]:
    """1 if distress in year+1/+2, 0 if not, None if the lookahead data is missing."""
    d, f, lv = debt.get(iso, {}), fiscal.get(iso, {}), levels.get(iso, {})
    signals: List[bool] = []
    have = False

    if year in d and (year + 2) in d:
        have = True
        signals.append(d[year + 2] - d[year] >= DEBT_JUMP_PP)
    for y in (year + 1, year + 2):
        g = _growth(lv, y)
        if g is not None:
            have = True
            signals.append(g < 0)
    if year in f and (year + 2) in f:
        have = True
        signals.append(f[year + 2] - f[year] <= -FISCAL_DROP_PP)

    if not have:
        return None
    return 1 if any(signals) else 0


SPIKE_FACTOR = 1.5


def _instability_spike(events: Dict[int, int], year: int) -> Optional[int]:
    """1 if instability surged in year+1/+2 vs the country's recent baseline.

    Baseline = mean instability events over [year-2, year] (needs ≥2 points). A
    spike is the forward count exceeding ``SPIKE_FACTOR`` × baseline. Within-country
    + forward-relative → robust to media-footprint differences and the secular rise
    in GDELT coverage. None when baseline or lookahead is missing.
    """
    recent = [events[y] for y in (year - 2, year - 1, year) if y in events]
    if len(recent) < 2:
        return None
    baseline = sum(recent) / len(recent)
    fwd = [events[y] for y in (year + 1, year + 2) if y in events]
    if not fwd:
        return None
    threshold = SPIKE_FACTOR * baseline
    return 1 if any(v > threshold for v in fwd) else 0


def label_panel_governance(panel: List[Dict], events: Dict[str, Dict[int, int]]) -> List[Dict]:
    """Attach an instability-spike *label* per panel row (governance outcome).

    *events* is ``{iso: {year: instability_event_count}}`` from GDELT (BigQuery).
    This is the construct the IRMP actually targets (political stability). It is
    independent of the historical IRMP, whose events dimension is held at STATIC
    declared values (not sourced from GDELT), so the label cannot leak from the
    score.
    """
    out: List[Dict] = []
    for row in panel:
        lab = _instability_spike(events.get(row["iso"], {}), row["year"])
        if lab is None:
            continue
        out.append({**row, "label": lab})
    return out


def label_panel(series: Dict, panel: List[Dict]) -> List[Dict]:
    """Attach a distress *label* to each panel row; drop rows with no lookahead."""
    debt = series.get("public_debt_gdp", {})
    fiscal = series.get("fiscal_balance_gdp", {})
    levels = series.get(WDI_GDP_LEVEL, {})
    out: List[Dict] = []
    for row in panel:
        lab = _distress(row["iso"], row["year"], debt, fiscal, levels)
        if lab is None:
            continue
        out.append({**row, "label": lab})
    return out
