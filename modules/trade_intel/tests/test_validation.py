"""Gate-E trade-resilience backtest — unit + integration (no network/fixture)."""
from modules.trade_intel.validation.historical import build_panel, resilience_band
from modules.trade_intel.validation.outcomes import (
    _export_collapse,
    _external_shock,
    label_panel_external,
)
from modules.trade_intel.validation.report import build_backtest_report

YEARS = ["2010", "2011", "2012", "2013"]


def _country_trade(concentrated: bool, collapse: bool) -> dict:
    """Build a country's trade matrix.

    concentrated → single export chapter + heavy imports (low resilience);
    diversified → 10 equal chapters + light imports (high resilience).
    collapse → export earnings fall 20%/yr; else flat.
    """
    out = {}
    for i, y in enumerate(YEARS):
        total = 100.0 * (0.8 ** i) if collapse else 100.0
        exports = {"01": total} if concentrated else {f"{j:02d}": total / 10 for j in range(1, 11)}
        imports = 900.0 if concentrated else 25.0
        out[y] = {"exports_by_chapter": exports, "imports_total": imports}
    return out


def _dataset(*, invert: bool = False) -> dict:
    """AA is the shocked country (export collapse + worsening CA); BB is calm.

    Normal: AA concentrated (LOW resilience) → the index ranks the collapse right.
    Invert: AA diversified (HIGH resilience) → the index ranks it wrong (negative).
    """
    aa_concentrated = not invert
    trade = {
        "AA": _country_trade(concentrated=aa_concentrated, collapse=True),
        "BB": _country_trade(concentrated=not aa_concentrated, collapse=False),
    }
    worsening = {"2010": 0.0, "2011": -5.0, "2012": -10.0, "2013": -15.0}  # ≥3pp drops
    stable = {y: 1.0 for y in YEARS}
    return {
        "trade": trade,
        "wdi": {
            "current_account_gdp": {"AA": worsening, "BB": stable},
            "reserves_import_months": {},
            "gdp_level": {},
        },
        "meta": {"years": [2010, 2023]},
    }


def test_resilience_band_thresholds():
    assert resilience_band(90) == "Fuerte"
    assert resilience_band(72) == "Sólido"
    assert resilience_band(60) == "Vigilar"
    assert resilience_band(30) == "Débil"
    assert resilience_band(None) is None


def test_build_panel_scores_each_country_year():
    by = {(r["iso"], r["year"]): r for r in build_panel(_dataset())}
    # AA: single chapter (HHI=1 → div=0) + 90% import dependency → very low resilience.
    assert by[("AA", 2010)]["resilience_score"] < 10
    assert by[("AA", 2010)]["band"] == "Débil"
    # BB: 10 equal chapters (div=90) + 20% dependency → high resilience.
    assert by[("BB", 2010)]["resilience_score"] > 80
    assert by[("BB", 2010)]["band"] == "Fuerte"


def test_export_collapse_detects_yoy_drop():
    exports = {"AA": {2010: 100.0, 2011: 80.0}}  # −20% YoY
    assert _export_collapse("AA", 2010, exports) == 1
    exports2 = {"AA": {2010: 100.0, 2011: 98.0}}  # −2% → no collapse
    assert _export_collapse("AA", 2010, exports2) == 0
    assert _export_collapse("AA", 2010, {"AA": {2010: 100.0}}) is None  # no lookahead


def test_external_outcome_drops_rows_without_lookahead():
    ca = {"AA": {"2010": 0.0, "2011": -5.0}}  # WDI year keys are strings
    # 2010 has t+1 (2011) → labeled; 2011 has no t+1/t+2 → None (dropped).
    assert _external_shock("AA", 2010, ca, {}, {}) == 1
    assert _external_shock("AA", 2011, ca, {}, {}) is None


def test_backtest_primary_is_export_collapse_and_discriminates():
    rep = build_backtest_report(_dataset())
    prim = rep["export_collapse"]  # PRIMARY
    assert rep["primary_outcome"] == "export_collapse"
    assert prim["n_observations"] == 6  # AA+BB × 2010-2012 (2013 dropped, no lookahead)
    assert prim["n_events"] == 3        # AA collapses each year
    assert prim["gini"] == 1.0          # low resilience perfectly ranks the collapse
    assert prim["monotonic"] is True
    assert "external_macro" in rep and rep["n_countries"] == 2


def test_backtest_inverted_gives_negative_gini():
    rep = build_backtest_report(_dataset(invert=True))
    # collapse now hits the HIGH-resilience country → index ranks it wrong.
    assert rep["export_collapse"]["gini"] == -1.0


def test_label_panel_external_attaches_label():
    ds = _dataset()
    labeled = label_panel_external(build_panel(ds), ds["wdi"])
    assert all("label" in r for r in labeled)
    assert {r["label"] for r in labeled} == {0, 1}
