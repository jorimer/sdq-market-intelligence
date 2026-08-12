"""Comparabilidad por cobertura: un score parcial no entra al orden global.

El caso: el Deep Dive de seguros afirmaba «posición 7 de 35» contando en esos 35 a
Reaseguradora Santo Domingo (74,6) y Seguros Crecer (70,4), cuyos ISF se arman sobre 3 de 5
dimensiones. Es el mismo problema que en banca se resolvió agrupando el ranking por tipo de
entidad: ordenar cosas que no son comparables.
"""
from shared.narrative.derived import (
    COBERTURA_COMPARABLE, rank_comparable, universo_comparable,
)

_PANEL = [
    {"slug": "cuna", "name": "Cuna Mutual", "overall_score": 82.4, "coverage": 1.0},
    {"slug": "reasanto", "name": "Reaseguradora", "overall_score": 74.6, "coverage": 0.65},
    {"slug": "ademi", "name": "Ademi", "overall_score": 73.7, "coverage": 1.0},
    {"slug": "mapfre", "name": "MAPFRE-BHD", "overall_score": 71.1, "coverage": 1.0},
    {"slug": "crecer", "name": "Crecer", "overall_score": 70.4, "coverage": 0.65},
    {"slug": "sin_score", "name": "Sin dato", "overall_score": None, "coverage": 1.0},
]


def test_los_parciales_salen_del_orden_pero_no_desaparecen():
    u = universo_comparable(_PANEL)
    assert [p["slug"] for p in u["comparables"]] == ["cuna", "ademi", "mapfre"]
    assert [p["slug"] for p in u["parciales"]] == ["reasanto", "crecer"]
    assert u["n_comparables"] == 3 and u["n_parciales"] == 2


def test_la_posicion_se_cuenta_solo_entre_comparables():
    """Con el panel entero MAPFRE era 4º; entre comparables es 3º. La cifra publicada
    cambia, y esa es exactamente la corrección."""
    pos = rank_comparable("mapfre", universo_comparable(_PANEL))
    assert pos["rank"] == 3 and pos["n_comparables"] == 3
    assert pos["comparable"] is True
    assert "quedan fuera del orden" in pos["criterio"]


def test_una_parcial_no_tiene_posicion_que_afirmar():
    pos = rank_comparable("crecer", universo_comparable(_PANEL))
    assert pos["rank"] is None and pos["comparable"] is False
    assert pos["n_parciales"] == 2


def test_sin_cobertura_declarada_se_trata_como_completo():
    """Un motor que no expone `coverage` no debe perder su ranking por una clave ausente."""
    panel = [{"slug": "a", "overall_score": 50.0}, {"slug": "b", "overall_score": 60.0}]
    u = universo_comparable(panel)
    assert u["n_comparables"] == 2 and u["n_parciales"] == 0
    assert rank_comparable("a", u)["rank"] == 2


def test_el_corte_es_cobertura_total_no_un_minimo_laxo():
    """Cualquier dimensión ausente cambia lo que el índice mide."""
    assert COBERTURA_COMPARABLE > 0.9
    u = universo_comparable([{"slug": "x", "overall_score": 1.0, "coverage": 0.95}])
    assert u["n_parciales"] == 1


def test_sirve_para_pensiones_buscando_por_nombre():
    """El deep dive de AFP encuentra su fila por `name`, no por `slug`."""
    pos = rank_comparable("MAPFRE-BHD", universo_comparable(_PANEL), clave_slug="name")
    assert pos["rank"] == 3
