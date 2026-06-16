"""Tests for the GDELT events connector (offline — HTTP mocked)."""
import pytest

from shared.data import gdelt_client as gc
from shared.data.gdelt_client import (
    GDELTApiError,
    GDELTClient,
    _avg,
    get_timeline,
    unrest_ratio,
)


class _FakeResp:
    def __init__(self, text):
        self.text = text
    def json(self):
        import json
        return json.loads(self.text)


# ── Pure helpers ────────────────────────────────────────────────

def test_avg_and_unrest_ratio_guards():
    assert _avg([1.0, 2.0, 3.0]) == 2.0
    assert _avg([]) is None
    # unrest = protest ÷ total coverage, capped at 100, None when undefined
    assert unrest_ratio(0.5, 2.0) == 25.0
    assert unrest_ratio(None, 2.0) is None
    assert unrest_ratio(1.0, 0.0) is None      # no total coverage
    assert unrest_ratio(5.0, 1.0) == 100.0     # capped


# ── Timeline parsing + rate-limit retry ─────────────────────────

def test_get_timeline_parses_values(monkeypatch):
    payload = '{"timeline":[{"data":[{"date":"x","value":2.5},{"date":"y","value":3.5}]}]}'
    monkeypatch.setattr(gc.httpx, "get", lambda *a, **k: _FakeResp(payload))
    assert get_timeline("q", "timelinetone") == [2.5, 3.5]


def test_get_timeline_empty_when_no_series(monkeypatch):
    monkeypatch.setattr(gc.httpx, "get", lambda *a, **k: _FakeResp('{"timeline":[]}'))
    assert get_timeline("q", "timelinevol") == []


def test_get_timeline_retries_then_succeeds(monkeypatch):
    calls = {"n": 0}
    def fake_get(*a, **k):
        calls["n"] += 1
        if calls["n"] == 1:
            return _FakeResp("Please limit requests to one every 5 seconds")
        return _FakeResp('{"timeline":[{"data":[{"date":"x","value":1.0}]}]}')
    monkeypatch.setattr(gc.httpx, "get", fake_get)
    monkeypatch.setattr(gc.time, "sleep", lambda *_a: None)   # don't actually wait
    assert get_timeline("q", "timelinetone") == [1.0]
    assert calls["n"] == 2


def test_get_timeline_raises_after_persistent_rate_limit(monkeypatch):
    monkeypatch.setattr(gc.httpx, "get", lambda *a, **k: _FakeResp("Please limit requests"))
    monkeypatch.setattr(gc.time, "sleep", lambda *_a: None)
    with pytest.raises(GDELTApiError):
        get_timeline("q", "timelinetone")


# ── Fixture mode ────────────────────────────────────────────────

def test_fixture_mode_two_vars_per_country():
    recs = GDELTClient(mode="fixture").fetch()
    assert recs
    assert {r.series for r in recs} == {"news_sentiment", "unrest_shocks"}
    assert len({r.dimension for r in recs}) == 5
    gt = [r for r in recs if r.dimension == "GT" and r.series == "news_sentiment"][0]
    assert gt.value == -10.0       # negative tone preserved
    assert gt.lineage.source == "GDELT"


def test_fixture_filter_by_series():
    recs = GDELTClient(mode="fixture").fetch(series="unrest_shocks")
    assert recs and all(r.series == "unrest_shocks" for r in recs) and len(recs) == 5
