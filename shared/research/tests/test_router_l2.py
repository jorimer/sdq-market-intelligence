"""Tests del cableado L2 (Redis) y corte de presupuesto en el router semántico."""
import asyncio
import json
from unittest.mock import MagicMock

import pytest

from shared.research import domain_router as dr


@pytest.fixture(autouse=True)
def _clear_l1():
    dr._ROUTE_CACHE.clear()
    yield
    dr._ROUTE_CACHE.clear()


def test_hit_l2_evita_el_llm(monkeypatch):
    payload = json.dumps([
        {"sector_key": "banking", "role": "primary", "reason": "pregunta de banca"},
        {"sector_key": "macro", "role": "context", "reason": "canal monetario"},
    ])
    monkeypatch.setattr(dr, "cache_get", lambda k: payload)

    def _no_llamar():
        raise AssertionError("con hit L2 no debe tocarse el cliente LLM")

    from shared.narrative.claude_engine import narrative_engine
    monkeypatch.setattr(narrative_engine, "_get_client", _no_llamar)

    routed = asyncio.run(dr.route_domains("¿como esta la banca?", None))
    assert [d.sector_key for d in routed] == ["banking", "macro"]
    assert routed[0].role == "primary"
    # promovido a L1: la misma pregunta ya no toca L2
    monkeypatch.setattr(dr, "cache_get", lambda k: None)
    routed2 = asyncio.run(dr.route_domains("¿como esta la banca?", None))
    assert [d.sector_key for d in routed2] == ["banking", "macro"]


def test_ruteo_exitoso_publica_en_l2(monkeypatch):
    published = {}
    monkeypatch.setattr(dr, "cache_get", lambda k: None)
    monkeypatch.setattr(dr, "cache_set", lambda k, v, ttl: published.update({k: v}))

    resp = MagicMock()
    resp.content = [MagicMock(text=json.dumps(
        {"dominios": [{"eje": "banking", "rol": "primario", "por_que": "x"}]}))]
    resp.usage = MagicMock(input_tokens=100, output_tokens=20)
    client = MagicMock()
    client.messages.create.return_value = resp

    from shared.narrative.claude_engine import narrative_engine
    monkeypatch.setattr(narrative_engine, "_get_client", lambda: client)

    routed = asyncio.run(dr.route_domains("pregunta de banca", None))
    assert [d.sector_key for d in routed] == ["banking"]
    assert len(published) == 1
    key = next(iter(published))
    assert key.startswith("route:v1:")
    stored = json.loads(published[key])
    assert stored[0]["sector_key"] == "banking"


def test_corte_de_presupuesto_cae_al_contexto_curado(monkeypatch):
    monkeypatch.setattr(dr, "cache_get", lambda k: None)
    from shared.narrative.claude_engine import narrative_engine
    monkeypatch.setattr(narrative_engine, "_get_client", lambda: MagicMock())
    monkeypatch.setattr(dr, "budget_allows", lambda: False)

    routed = asyncio.run(dr.route_domains("pregunta cualquiera", None))
    assert routed == []


def test_l2_corrupta_no_rompe(monkeypatch):
    monkeypatch.setattr(dr, "cache_get", lambda k: "{corrupto")
    from shared.narrative.claude_engine import narrative_engine
    monkeypatch.setattr(narrative_engine, "_get_client", lambda: None)
    routed = asyncio.run(dr.route_domains("otra pregunta", None))
    assert routed == []
