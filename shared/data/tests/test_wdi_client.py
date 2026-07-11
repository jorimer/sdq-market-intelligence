"""Tests for the WDI + IMF WEO live connector (offline — HTTP mocked)."""
import pytest

from shared.data import wdi_client as wc
from shared.data.wdi_client import (
    ISO3_TO_ISO2,
    WDIApiError,
    WDIClient,
    WDI_GDP_LEVEL,
    WDI_INFLATION,
    _cagr,
    _fx_volatility,
    _latest_year_at_or_before,
    declared_sovereign_records,
    fetch_imf_indicator,
)


# ── Pure helpers ────────────────────────────────────────────────

def test_cagr_math_and_guards():
    assert _cagr(100.0, 110.0, 3) == 3.23      # (110/100)^(1/3)-1
    assert _cagr(0.0, 110.0, 3) is None        # non-positive base
    assert _cagr(100.0, None, 3) is None        # missing endpoint


def test_fx_volatility_proxy_and_guards():
    # Dollarized (flat) → 0.0; needs ≥3 points; None when too short.
    assert _fx_volatility({2022: 1.0, 2023: 1.0, 2024: 1.0}) == 0.0
    assert _fx_volatility({2023: 100.0, 2024: 110.0}) is None     # only 1 change
    rising = {2021: 100.0, 2022: 110.0, 2023: 121.0, 2024: 133.1}  # steady +10%/yr
    assert _fx_volatility(rising) == 0.0                          # constant rate → σ=0


def test_declared_sovereign_records_map_ratings_to_scores():
    recs = declared_sovereign_records("2024")
    by = {r.dimension: r for r in recs}
    assert set(by) == {"DO", "CR", "PA", "GT", "JM"}
    assert all(r.series == "sovereign_rating_score" for r in recs)
    assert all(r.period == "2024" for r in recs)
    assert by["PA"].value == 55.0      # BBB- (investment grade, highest of peers)
    assert by["DO"].value == 45.0      # BB
    assert by["GT"].value == 50.0      # BB+
    assert by["PA"].lineage.source == "SDQ_DECLARED"


def test_latest_year_at_or_before_caps_forecasts():
    obs = {"2023": 50.0, "2024": 55.0, "2025": 60.0}   # 2025 = WEO forecast
    assert _latest_year_at_or_before(obs, 2024) == 2024
    assert _latest_year_at_or_before({"2023": None, "2024": 55.0}, 2024) == 2024  # skip None
    assert _latest_year_at_or_before({"2030": 1.0}, 2024) is None                 # all > cap


def test_inflation_targets_come_from_doctrine():
    targets = WDIClient()._inflation_targets()
    assert targets["DO"] == 4.0 and targets["PA"] == 2.0
    assert set(targets) == {"DO", "CR", "PA", "GT", "JM"}


# ── Fixture mode ────────────────────────────────────────────────

def test_fixture_mode_records_carry_country_in_dimension():
    recs = WDIClient(mode="fixture").fetch()
    assert recs
    do_ca = [r for r in recs if r.dimension == "DO" and r.series == "current_account_gdp"]
    assert len(do_ca) == 1 and do_ca[0].value == -3.35 and do_ca[0].period == "2024"
    assert len({r.dimension for r in recs}) == 5   # 5 peer countries


def test_fixture_filter_by_series():
    rl = WDIClient(mode="fixture").fetch(series="fdi_gdp")
    assert rl and all(r.series == "fdi_gdp" for r in rl) and len(rl) == 5


# ── Live parsing (mocked) ───────────────────────────────────────

def _mock_wb(code, iso3, **kw):
    if code == WDI_GDP_LEVEL:                      # 4 constant-GDP levels for DOM
        return ([{"countryiso3code": "DOM", "date": str(y), "value": v}
                 for y, v in {"2021": 100.0, "2022": 103.0, "2023": 106.0, "2024": 110.0}.items()],
                "2025-07-01")
    if code == WDI_INFLATION:                      # DOM inflation 6.0 → gap vs target 4.0 = 2.0
        return ([{"countryiso3code": "DOM", "date": "2024", "value": 6.0}], "2025-07-01")
    # direct vars
    return ([{"countryiso3code": "DOM", "date": "2024", "value": 5.0}], "2025-07-01")


def _mock_imf(code, **kw):                          # 2025 is a forecast → must be excluded
    return {"DOM": {"2023": 50.0, "2024": 55.0, "2025": 60.0}}


def test_live_derives_cagr_gap_and_caps_imf_forecast(monkeypatch):
    monkeypatch.setattr(wc, "fetch_wb_indicator", _mock_wb)
    monkeypatch.setattr(wc, "fetch_imf_indicator", _mock_imf)
    recs = WDIClient(mode="live").fetch()
    by = {(r.dimension, r.series): r for r in recs}

    # gdp_cagr_3y from levels: (110/100)^(1/3)-1 = 3.23
    assert by[("DO", "gdp_cagr_3y")].value == 3.23
    assert by[("DO", "gdp_cagr_3y")].period == "2024"
    # inflation_gap = |6.0 - 4.0| = 2.0
    assert by[("DO", "inflation_gap")].value == 2.0
    # IMF capped at WDI ref year (2024) → 55.0, NOT the 2025 forecast (60.0)
    assert by[("DO", "public_debt_gdp")].value == 55.0
    assert by[("DO", "public_debt_gdp")].period == "2024"
    assert by[("DO", "public_debt_gdp")].lineage.source == "IMF_WEO"


def test_live_skips_imf_when_no_wdi_reference_year(monkeypatch):
    # WDI GDP unavailable → no reference year → IMF skipped (no forecast leak).
    def wb(code, iso3, **kw):
        if code == WDI_GDP_LEVEL:
            raise WDIApiError("gdp down")
        return ([], None)
    imf_called = {"n": 0}
    def imf(code, **kw):
        imf_called["n"] += 1
        return {"DOM": {"2025": 99.0}}  # only a forecast available
    monkeypatch.setattr(wc, "fetch_wb_indicator", wb)
    monkeypatch.setattr(wc, "fetch_imf_indicator", imf)
    recs = WDIClient(mode="live").fetch()
    assert imf_called["n"] == 0                       # IMF never queried
    assert not any(r.lineage.source == "IMF_WEO" for r in recs)


def test_live_missing_inflation_value_yields_none_gap(monkeypatch):
    def wb(code, iso3, **kw):
        if code == WDI_INFLATION:
            return ([{"countryiso3code": "DOM", "date": "2024", "value": None}], None)
        return ([], None)
    monkeypatch.setattr(wc, "fetch_wb_indicator", wb)
    monkeypatch.setattr(wc, "fetch_imf_indicator", lambda code, **k: {})
    recs = WDIClient(mode="live").fetch(series="inflation_gap")
    assert recs and recs[0].value is None          # never fabricated


# ── HTTP error shapes ───────────────────────────────────────────

class _FakeResp:
    def __init__(self, payload):
        self._p = payload
    def raise_for_status(self):
        pass
    def json(self):
        return self._p


def test_fetch_imf_raises_on_bad_shape(monkeypatch):
    monkeypatch.setattr(wc.httpx, "get", lambda *a, **k: _FakeResp({"nope": {}}))
    with pytest.raises(WDIApiError):
        fetch_imf_indicator("GGXWDG_NGDP")


def test_fetch_imf_parses_ok_shape(monkeypatch):
    payload = {"values": {"GGXWDG_NGDP": {"DOM": {"2024": 59.4}}}}
    monkeypatch.setattr(wc.httpx, "get", lambda *a, **k: _FakeResp(payload))
    out = fetch_imf_indicator("GGXWDG_NGDP")
    assert out["DOM"]["2024"] == 59.4


def test_iso_map_is_consistent():
    # Panel LatAm+Caribe completo (24, fuente única shared.data.latam_peers).
    assert ISO3_TO_ISO2["DOM"] == "DO" and ISO3_TO_ISO2["VEN"] == "VE"
    assert len(ISO3_TO_ISO2) == 24
