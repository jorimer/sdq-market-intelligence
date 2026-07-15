"""SPEC-1 + SPEC-7 — completitud de ejes del motor de research.

Un eje "convocable" necesita los TRES registros: `CatalogEntry` (catálogo de productos),
summarizer dedicado (`_AXIS_SUMMARY`) y keywords de ruteo léxico (`AXIS_KEYWORDS`). Si tiene
summarizer pero le faltan keywords, el router nunca lo alcanza y la pregunta cae a scoping con
cobertura 0 — el bug real que tuvo `agribusiness` (y antes `insurance`). Este guard falla en CI si
vuelve a ocurrir con cualquier eje futuro (patrón "no silent gaps").
"""
from __future__ import annotations

from shared.research.data_pull import _AXIS_SUMMARY, _generic_summary
from shared.research.resolve import AXIS_KEYWORDS, detect_axes


def test_every_dedicated_axis_has_routing_keywords():
    """SPEC-7: todo eje con summarizer DEDICADO (no el genérico) debe tener keywords no vacías.
    Sin keywords, `detect_axes` no lo selecciona jamás → scoping silencioso."""
    missing = [
        key for key, summ in _AXIS_SUMMARY.items()
        if summ is not _generic_summary and not AXIS_KEYWORDS.get(key)
    ]
    assert not missing, (
        "Ejes con summarizer dedicado pero SIN keywords de ruteo (caerían a scoping "
        f"con cobertura 0): {missing}. Añádeles una entrada en AXIS_KEYWORDS."
    )


def test_agribusiness_routes_from_natural_sector_question():
    """SPEC-1: una pregunta natural de sector agro resuelve el eje agribusiness (antes: scoping)."""
    for q in (
        "¿Qué situación tiene el sector agropecuario en República Dominicana?",
        "¿Cómo va la agroindustria dominicana?",
        "desempeño del sector agrícola y su índice IAI",
    ):
        assert "agribusiness" in detect_axes(q), f"agro no ruteó a agribusiness: {q!r}"


def test_agro_keyword_does_not_false_match_unrelated_words():
    """El stem 'agro' está anclado a frontera de palabra: no debe activar en 'milagro'/'logro'."""
    assert "agribusiness" not in detect_axes("fue un milagro lograr ese resultado")
