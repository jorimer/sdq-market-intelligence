"""Tests for the WGI live connector (offline — HTTP mocked)."""
from datetime import date

import pytest

from shared.data import wgi_client as wc
from shared.data.wgi_client import ISO3_TO_ISO2, WGIApiError, WGIClient, fetch_wgi_indicator


# ── Fixture mode ────────────────────────────────────────────────

def test_fixture_mode_records_carry_country_in_dimension():
    recs = WGIClient(mode="fixture").fetch()
    assert recs
    do_rl = [r for r in recs if r.dimension == "DO" and r.series == "wgi_rule_of_law"]
    assert len(do_rl) == 1
    r = do_rl[0]
    assert r.value == 53.83
    assert r.unit == "percentil 0-100"
    assert r.period == "2024"
    assert r.lineage.source == "WGI"
    assert len({r.dimension for r in recs}) == 5   # 5 peer countries
    assert len({r.series for r in recs}) == 6       # 6 WGI variables (RL/GE/CC/PV/VA/RQ)


def test_fixture_filter_by_series_and_period():
    c = WGIClient(mode="fixture")
    rl = c.fetch(series="wgi_political_stability")
    assert rl and all(r.series == "wgi_political_stability" for r in rl)
    assert len(rl) == 5
    assert c.fetch(period="1999") == []  # no such year


# ── Live parsing (mocked) ───────────────────────────────────────

def test_live_parses_rows_iso_mapping_and_nulls(monkeypatch):
    rows = [
        {"countryiso3code": "DOM", "date": "2023", "value": 42.1},
        {"countryiso3code": "CRI", "date": "2023", "value": None},  # missing → None
    ]
    monkeypatch.setattr(wc, "fetch_wgi_indicator", lambda code, iso3, **kw: (rows, "2024-09-19"))
    recs = WGIClient(mode="live").fetch(series="wgi_rule_of_law")
    by_country = {r.dimension: r for r in recs}
    assert set(by_country) == {"DO", "CR"}            # ISO3 → ISO2
    assert by_country["DO"].value == 42.1
    assert by_country["CR"].value is None             # never interpolated
    assert by_country["DO"].period == "2023"
    assert by_country["DO"].lineage.published_at == date(2024, 9, 19)
    assert by_country["DO"].unit == "percentil 0-100"


def test_live_skips_a_failing_indicator(monkeypatch):
    def flaky(code, iso3, **kw):
        if code == "GOV_WGI_RL.SC":
            raise WGIApiError("boom")
        return [{"countryiso3code": "DOM", "date": "2023", "value": 50.0}], None
    monkeypatch.setattr(wc, "fetch_wgi_indicator", flaky)
    recs = WGIClient(mode="live").fetch()
    # RL failed → the other five variables present, endpoint didn't break
    assert "wgi_rule_of_law" not in {r.series for r in recs}
    assert {r.series for r in recs} == {
        "wgi_gov_effectiveness", "wgi_control_corruption",
        "wgi_political_stability", "wgi_voice_accountability", "wgi_regulatory_quality",
    }


# ── HTTP error shape ────────────────────────────────────────────

class _FakeResp:
    def __init__(self, payload):
        self._p = payload
    def raise_for_status(self):
        pass
    def json(self):
        return self._p


def test_fetch_indicator_raises_on_error_shape(monkeypatch):
    # WB returns a single-element list with a "message" when the indicator is bad.
    monkeypatch.setattr(wc.httpx, "get",
                        lambda *a, **k: _FakeResp([{"message": [{"value": "not found"}]}]))
    with pytest.raises(WGIApiError):
        fetch_wgi_indicator("BAD.CODE", ["DOM"])


def test_fetch_indicator_parses_ok_shape(monkeypatch):
    payload = [{"lastupdated": "2024-09-19", "total": 1},
               [{"countryiso3code": "DOM", "date": "2023", "value": 42.1}]]
    monkeypatch.setattr(wc.httpx, "get", lambda *a, **k: _FakeResp(payload))
    rows, last = fetch_wgi_indicator("GOV_WGI_RL.SC", ["DOM"])
    assert last == "2024-09-19"
    assert rows[0]["value"] == 42.1


def test_iso_map_is_consistent():
    assert ISO3_TO_ISO2["DOM"] == "DO"
    assert len(ISO3_TO_ISO2) == 5
