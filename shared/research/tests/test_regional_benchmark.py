"""SPEC-6 — comparación regional (Centroamérica + Caribe) desde WDI.

Fetcher inyectable → sin red. Cubre: agregación RD vs promedio de pares, ruteo por intención
regional, el pull con la línea de LÍMITE honesto, y la degradación a None si el WDI no responde.
"""
from __future__ import annotations

import shared.research.regional_benchmark as rb
from shared.research.data_pull import pull_regional_benchmark
from shared.research.regional_benchmark import build_regional_comparison
from shared.research.resolve import detect_axes


def _fake_fetch(dom_val, peer_val, growth_dom=5.0, growth_peer=3.0):
    """Fetcher falso: DOM y cada par devuelven un valor fijo por indicador."""
    def fetch(indicator, iso3s, mrv):
        v = {rb.WDI_GDP_GROWTH: (growth_dom, growth_peer)}.get(indicator, (dom_val, peer_val))
        rows = [{"countryiso3code": iso, "date": "2024",
                 "value": (v[0] if iso == "DOM" else v[1])} for iso in iso3s]
        return rows, "2025-06-01"
    return fetch


def test_regional_peers_are_ca_and_caribbean_without_dom():
    iso3 = rb.regional_peers_iso3()
    assert "DOM" not in iso3
    assert {"CRI", "PAN", "GTM", "JAM", "SLV", "HND", "NIC", "TTO"} <= set(iso3)


def test_build_computes_dom_vs_regional_average():
    data = build_regional_comparison(fetch=_fake_fetch(dom_val=10.0, peer_val=4.0))
    assert data is not None
    comp = {c["sector"]: c for c in data["composition"]}
    assert comp["Agricultura"]["dom"] == 10.0
    assert comp["Agricultura"]["region_avg"] == 4.0     # todos los pares valen 4.0
    assert comp["Agricultura"]["n_peers"] >= 8
    assert data["growth"]["dom"] == 5.0 and data["growth"]["region_avg"] == 3.0


def test_none_when_wdi_unreachable():
    def boom(indicator, iso3s, mrv):
        raise RuntimeError("WDI caído")
    assert build_regional_comparison(fetch=boom) is None


def test_detect_axes_routes_regional_intent():
    for q in ("¿cómo se compara con el promedio de Centroamérica y el Caribe?",
              "el desempeño dominicano frente a la región",
              "vs pares regionales"):
        assert "regional_benchmark" in detect_axes(q), q


def test_pull_declares_the_honest_limit(monkeypatch):
    """El pull SIEMPRE declara que el WDI no desagrega minería/turismo/construcción cross-country."""
    monkeypatch.setattr(rb, "build_regional_comparison", lambda: {
        "composition": [{"sector": "Servicios", "dom": 60.0, "region_avg": 55.0,
                         "n_peers": 9, "year": 2024}],
        "growth": {"dom": 5.0, "region_avg": 3.0, "n_peers": 9, "year": 2024},
        "year": 2024, "source": rb.REGIONAL_SOURCE,
    })
    pull = pull_regional_benchmark()
    assert pull is not None and pull.ok
    joined = " ".join(e.text.lower() for e in pull.evidence)
    assert "no permite comparar minería" in joined or "no permite comparar mineria" in joined
    assert "servicios rd 60" in joined


def test_pull_none_degrades(monkeypatch):
    monkeypatch.setattr(rb, "build_regional_comparison", lambda: None)
    assert pull_regional_benchmark() is None


def test_regional_pull_attaches_in_compound_question():
    """El pull regional debe adherir a la sub-pregunta de comparación en una pregunta COMPUESTA.

    Bug hallado en verificación de prod: el entity_label "Comparación regional (CA y Caribe)" daba
    el token "caribe)" (con paréntesis) que no estaba en la sub-pregunta → la comparación regional
    quedaba como brecha pese a que el eje traía dato. En preguntas de UNA sub-pregunta lo salvaba el
    fallback de _merge_engine_evidence; en las compuestas, no.
    """
    from shared.research.data_pull import EnginePull
    from shared.research.models import SubQuestion
    from shared.research.orchestrator import _matches_pull

    pull = EnginePull(sector_key="regional_benchmark",
                      entity_label="Comparación regional (CA y Caribe)",
                      period="2025", source="WDI", ok=True)
    regional_sq = SubQuestion(
        text="cómo se compara ese desempeño con el promedio de Centroamérica y el Caribe")
    mining_sq = SubQuestion(text="qué papel juega la minería en el crecimiento dominicano")
    assert _matches_pull(regional_sq, pull), "el pull regional no adhirió a la sub-pregunta regional"
    assert not _matches_pull(mining_sq, pull), "el pull regional NO debe adherir a minería"
