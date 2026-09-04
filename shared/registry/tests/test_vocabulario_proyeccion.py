"""`PROJECTED` entra al vocabulario, y lo desconocido sigue cayendo a `GAP`.

La regla dura del registro es que un estado que no se reconoce se declara brecha: nunca se
asume que hay dato. Sumar un cuarto estado no puede aflojar eso — si una cadena rara
escalara a `PROJECTED`, cualquier basura quedaría anclada.
"""
import pytest

from shared.registry.signals import GAP, PROJECTED, STATES, normalize_state


@pytest.mark.parametrize("alias", ["projected", "proyeccion", "proyección", "forecast",
                                   "nowcast", "PROJECTED", "  Forecast  "])
def test_los_alias_mapean_a_projected(alias):
    assert normalize_state(alias) == PROJECTED


@pytest.mark.parametrize("raro", ["proyectadísimo", "quizás", "", None, "estimado", "real-ish"])
def test_lo_desconocido_sigue_cayendo_a_gap(raro):
    assert normalize_state(raro) == GAP


def test_los_cuatro_estados_estan_declarados():
    assert len(STATES) == 4
    assert PROJECTED in STATES
