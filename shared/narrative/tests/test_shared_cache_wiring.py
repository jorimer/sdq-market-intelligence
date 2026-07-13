"""Tests del cableado L2 (Redis) y corte de presupuesto en el motor de narrativa."""
import asyncio
import json
from unittest.mock import MagicMock

import pytest

from shared.narrative import claude_engine as ce
from shared.narrative.claude_engine import NarrativeEngine, NarrativeResult


@pytest.fixture()
def engine():
    return NarrativeEngine()


def test_set_cache_publica_en_l2(engine, monkeypatch):
    published = {}
    monkeypatch.setattr(ce, "cache_set", lambda k, v, ttl: published.update({k: (v, ttl)}))
    result = NarrativeResult(text="hola", tokens_used=10, cost_estimate=0.01,
                             model_used="claude-sonnet-4-6")
    engine._set_cache("abc", result)
    key, (payload, ttl) = next(iter(published.items()))
    assert key == "narr:v1:abc"
    assert ttl == ce.CACHE_TTL_SECONDS
    data = json.loads(payload)
    assert data["text"] == "hola"
    assert data["model_used"] == "claude-sonnet-4-6"


def test_fallback_estatico_no_va_a_l2(engine, monkeypatch):
    published = {}
    monkeypatch.setattr(ce, "cache_set", lambda k, v, ttl: published.update({k: v}))
    engine._set_cache("abc", NarrativeResult(text="x", model_used="static_fallback"))
    assert not published  # solo L1
    assert "abc" in engine._cache


def test_get_cached_cae_a_l2_y_promueve(engine, monkeypatch):
    payload = json.dumps({
        "text": "narrativa compartida", "tokens_used": 42, "cost_estimate": 0.05,
        "model_used": "claude-sonnet-4-6", "guard_unsupported": [],
    })
    monkeypatch.setattr(ce, "cache_get", lambda k: payload if k == "narr:v1:xyz" else None)
    result = engine._get_cached("xyz")
    assert result is not None
    assert result.text == "narrativa compartida"
    assert result.from_cache is True
    assert "xyz" in engine._cache  # promovido a L1


def test_l2_corrupta_se_ignora(engine, monkeypatch):
    monkeypatch.setattr(ce, "cache_get", lambda k: "{no es json")
    assert engine._get_cached("xyz") is None


def test_generate_degrada_a_estatico_por_presupuesto(engine, monkeypatch):
    monkeypatch.setattr(ce, "cache_get", lambda k: None)
    monkeypatch.setattr(ce, "cache_set", lambda *a, **k: None)
    monkeypatch.setattr(engine, "_get_client", lambda: MagicMock())
    monkeypatch.setattr(ce, "budget_allows", lambda: False)

    result = asyncio.run(engine.generate({"dato": 1}, template="executive_summary"))
    assert result.model_used == "static_fallback"
    # NO se cachea: al liberarse presupuesto, la próxima request regenera de verdad
    assert engine._cache == {}
