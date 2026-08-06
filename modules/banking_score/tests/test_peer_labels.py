"""Rótulos del bloque de pares: la métrica se NOMBRA, no se deduce.

El campo `score` a secas no decía de qué era el puntaje, y la §Análisis Comparativo lo
rotuló como "solidez financiera" —el sub-componente de 40%— contradiciendo la tabla del
propio informe, donde esa dimensión marca 100/100 y percentil 100.
"""
from modules.banking_score.reports.narrative import _build_section_context

_BENCH = {
    "named_peers": {
        "entity_type": "banca_multiple",
        "n_system": 86, "n_type": 16,
        "ranking_por": "calificación global (0-100), NO un sub-componente",
        "rows": [
            {"name": "BDI", "overall_score": 91.55, "tier": "SDQ-AA+", "rank": 1},
            {"name": "Banco Popular Dominicano", "overall_score": 91.14,
             "tier": "SDQ-AA+", "rank": 2, "is_subject": True},
        ],
        "posiciones_dimension": {
            "Solidez Financiera": {"rank": 1, "n": 16, "es_lider": True,
                                   "lider": "Banco Popular Dominicano"},
            "Liquidez": {"rank": 12, "n": 16, "es_lider": False, "lider": "BDI"},
        },
    }
}
_SCORING = {"overall_score": 91.14, "rating_tier": "SDQ-AA+",
            "sub_components": {"solidez": 100.0}, "indicators": {}}


def test_las_filas_nombran_la_metrica():
    """`overall_score`, no `score`: el nombre del campo es la mitad del dato."""
    for row in _BENCH["named_peers"]["rows"]:
        assert "overall_score" in row
        assert "score" not in row


def test_el_contexto_declara_por_que_se_ordena():
    ctx = _build_section_context("comparative", "BPD", _SCORING, "2025-12-31", _BENCH)
    np = ctx["benchmarks"]["named_peers"]
    assert "sub-componente" in np["ranking_por"]


def test_posiciones_dimension_se_eleva_al_nivel_superior():
    """El veto de superlativos de numeric_guard la lee en la raíz del contexto; si queda
    anidada bajo los pares, el patrón se salta entero."""
    ctx = _build_section_context("comparative", "BPD", _SCORING, "2025-12-31", _BENCH)
    assert ctx["posiciones_dimension"]["Solidez Financiera"]["es_lider"] is True
    assert ctx["posiciones_dimension"]["Liquidez"]["es_lider"] is False


def test_sin_pares_no_hay_posiciones():
    ctx = _build_section_context("comparative", "BPD", _SCORING, "2025-12-31", {})
    assert "posiciones_dimension" not in ctx
