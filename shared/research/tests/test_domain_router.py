"""Tests del enrutador semántico de dominios (Mejora #1).

Cubren la lógica DETERMINISTA (parseo, validación contra el catálogo, merge aditivo) sin
llamar al Cerebro, y la degradación transparente cuando no hay API key.
"""
import pytest

import shared.research.domain_router as dr
from shared.research.resolve import ResolvedEntity, Targets


def test_extract_obj_tolerates_fences_and_prose():
    raw = 'Claro, aquí va:\n```json\n{"dominios": [{"eje": "macro", "rol": "contexto"}]}\n```\n'
    obj = dr._extract_obj(raw)
    assert obj and obj["dominios"][0]["eje"] == "macro"


def test_extract_obj_returns_none_on_garbage():
    assert dr._extract_obj("no hay json aquí") is None
    assert dr._extract_obj("") is None


def test_parse_domains_validates_against_catalog():
    # 'banking' y 'macro' son reales/implementados; 'crypto' es inventado → se descarta.
    obj = {"dominios": [
        {"eje": "banking", "rol": "primario", "por_que": "trata del banco"},
        {"eje": "crypto", "rol": "contexto", "por_que": "inventado"},
        {"eje": "macro", "rol": "contexto", "por_que": "condiciones sistémicas"},
    ]}
    out = dr._parse_domains(obj)
    keys = {d.sector_key for d in out}
    assert "banking" in keys and "macro" in keys
    assert "crypto" not in keys  # anti-fabricación
    banking = next(d for d in out if d.sector_key == "banking")
    assert banking.role == "primary" and banking.reason


def test_parse_domains_dedupes_and_caps():
    obj = {"dominios": [{"eje": "macro", "rol": "contexto"}] * 3
           + [{"eje": "banking", "rol": "primario"}]}
    out = dr._parse_domains(obj)
    assert [d.sector_key for d in out].count("macro") == 1
    assert len(out) <= dr._MAX_DOMAINS


def test_catalog_menu_lists_engines_by_key():
    menu = dr._catalog_menu()
    # el menú lista por clave 'eje'; al menos banca/macro/monetario deben aparecer.
    assert "banking:" in menu and "macro:" in menu and "monetary_policy:" in menu


def test_merge_routing_is_additive_and_records_reasons():
    t = Targets(axes=[], entities=[ResolvedEntity("banking", "id1", "Banco Lafise")],
                context=["macro"])  # 'macro' ya sembrado por el mapa curado
    routed = [
        dr.RoutedDomain("banking", "primary", "trata del banco"),      # cubierto por entidad
        dr.RoutedDomain("macro", "context", "riesgo-país"),            # ya en context (no dup)
        dr.RoutedDomain("monetary_policy", "context", "canal de fondeo"),  # nuevo contexto
    ]
    dr.merge_routing(t, routed)
    assert t.context.count("macro") == 1          # no duplica lo curado
    assert "monetary_policy" in t.context          # agrega el nuevo dominio
    assert "banking" not in t.axes and "banking" not in t.context  # ya lo trae la entidad
    # razones registradas para narrar el canal de transmisión
    assert t.reasons["monetary_policy"] == "canal de fondeo"
    assert t.reasons["banking"] == "trata del banco"


def test_merge_routing_primary_without_entity_goes_to_axes():
    t = Targets(axes=[], entities=[], context=[])
    dr.merge_routing(t, [dr.RoutedDomain("trade", "primary", "trata de comercio")])
    assert "trade" in t.axes


def test_merge_routing_noop_on_empty():
    t = Targets(axes=["banking"], entities=[], context=["macro"])
    dr.merge_routing(t, [])
    assert t.axes == ["banking"] and t.context == ["macro"] and t.reasons == {}


@pytest.mark.asyncio
async def test_route_domains_degrades_without_client(monkeypatch):
    # Sin API key el motor no tiene cliente → lista vacía (fallback al contexto curado).
    from shared.narrative.claude_engine import narrative_engine
    monkeypatch.setattr(narrative_engine, "_get_client", lambda: None)
    out = await dr.route_domains("riesgo de liquidez de Banco Lafise", db=object())
    assert out == []


@pytest.mark.asyncio
async def test_route_domains_parses_a_mocked_cerebro_response(monkeypatch):
    from shared.narrative.claude_engine import narrative_engine

    class _Block:
        text = '{"dominios": [{"eje": "banking", "rol": "primario", "por_que": "el banco"}, ' \
               '{"eje": "monetary_policy", "rol": "contexto", "por_que": "fondeo"}]}'

    class _Resp:
        content = [_Block()]

    class _Client:
        class messages:
            @staticmethod
            def create(**kw):
                return _Resp()

    monkeypatch.setattr(narrative_engine, "_get_client", lambda: _Client())
    out = await dr.route_domains("perfil de riesgo de Banco Lafise", db=object())
    keys = {d.sector_key for d in out}
    assert keys == {"banking", "monetary_policy"}
    assert next(d for d in out if d.sector_key == "monetary_policy").role == "context"


@pytest.mark.asyncio
async def test_route_domains_caches_by_question(monkeypatch):
    """El ruteo se cachea por pregunta (y va con temperature=0): misma pregunta → mismos
    dominios SIN segunda llamada LLM. Sin esto, la variación del router rompía la caché de
    narrativas aguas abajo (cada re-consulta idéntica pagaba el LLM completo)."""
    from shared.narrative.claude_engine import narrative_engine
    monkeypatch.setattr(dr, "_ROUTE_CACHE", {})
    calls = {"n": 0, "kwargs": None}

    class _Block:
        text = '{"dominios": [{"eje": "macro", "rol": "contexto", "por_que": "ciclo"}]}'

    class _Resp:
        content = [_Block()]

    class _Client:
        class messages:
            @staticmethod
            def create(**kw):
                calls["n"] += 1
                calls["kwargs"] = kw
                return _Resp()

    monkeypatch.setattr(narrative_engine, "_get_client", lambda: _Client())
    q = "impacto del ciclo en las zonas francas orientales"
    out1 = await dr.route_domains(q, db=object())
    out2 = await dr.route_domains(q.upper() + "  ", db=object())  # normaliza espacios/caso
    assert calls["n"] == 1, "la 2ª llamada debe salir del caché"
    assert [d.sector_key for d in out1] == [d.sector_key for d in out2] == ["macro"]
    assert calls["kwargs"]["temperature"] == 0.0


@pytest.mark.asyncio
async def test_route_domains_does_not_cache_failures(monkeypatch):
    """Un fallo del API no se cachea: la próxima consulta reintenta."""
    from shared.narrative.claude_engine import narrative_engine
    monkeypatch.setattr(dr, "_ROUTE_CACHE", {})

    class _Boom:
        class messages:
            @staticmethod
            def create(**kw):
                raise RuntimeError("api caída")

    monkeypatch.setattr(narrative_engine, "_get_client", lambda: _Boom())
    q = "pregunta que falla transitoriamente"
    assert await dr.route_domains(q, db=object()) == []
    assert dr._route_cache_key(q) not in dr._ROUTE_CACHE
