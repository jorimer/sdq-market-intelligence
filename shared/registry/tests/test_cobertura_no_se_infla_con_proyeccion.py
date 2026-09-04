"""El test que gobierna todo el bloque: una proyección NO sube la cobertura real.

`PROJECTED` es un cuarto estado entre «tengo el dato» y «declaro la brecha». Sirve para que
una pregunta prospectiva pueda anclarse en un pronóstico con backtest en vez de morir en
brecha. Lo que NO puede hacer es inflar la métrica con la que la plataforma dice cuánto de
un índice está sostenido por dato real: un producto que hoy reporta 62% de cobertura real
tiene que seguir reportando 62% mañana, con proyecciones y todo.

Si algún número se mueve, es un bug. Por eso este test convierte una señal `GAP` en
`PROJECTED` y compara `coverage_real` ANTES y DESPUÉS: idéntico, no «parecido».

`coverage_projected` es una propiedad HERMANA. Se reporta al lado y jamás se suma.
"""
import pytest

from shared.registry.signals import (
    GAP,
    PROJECTED,
    REAL,
    RUBRIC,
    AxisRegistry,
    DataRegistry,
    VariableSignal,
)


def _eje(estados_y_pesos):
    señales = tuple(
        VariableSignal(key=f"v{i}", label=f"V{i}", state=estado, weight=peso,
                       real_fraction=frac)
        for i, (estado, peso, frac) in enumerate(estados_y_pesos)
    )
    return AxisRegistry(sector_key="x", display_name="X", source="s", implemented=True,
                        signals=señales)


_MIXTO = [(REAL, 0.5, 1.0), (RUBRIC, 0.2, 1.0), (GAP, 0.2, 1.0), (REAL, 0.1, 0.5)]


def test_convertir_un_gap_en_proyeccion_no_mueve_la_cobertura_real():
    antes = _eje(_MIXTO)
    cov_antes = antes.coverage_real
    despues = _eje([(PROJECTED, 0.2, 1.0) if e == GAP else (e, p, f)
                    for e, p, f in _MIXTO])
    assert despues.coverage_real == cov_antes, (
        f"la cobertura real se movió de {cov_antes} a {despues.coverage_real} al declarar "
        "una proyección: una proyección no es dato real")


def test_la_cobertura_proyectada_sube_y_vive_aparte():
    antes = _eje(_MIXTO)
    despues = _eje([(PROJECTED, 0.2, 1.0) if e == GAP else (e, p, f)
                    for e, p, f in _MIXTO])
    assert antes.coverage_projected == 0.0
    assert despues.coverage_projected > 0.0
    assert despues.coverage_projected == pytest.approx(0.2)


def test_la_proyectada_acredita_su_fraccion_y_no_uno_plano():
    """Simetría con `_real_credit`: en un panel donde solo algunos sujetos se proyectan, una
    señal parcialmente cubierta cuenta parcialmente. Un `1.0` plano sobreestimaría."""
    eje = _eje([(PROJECTED, 1.0, 0.25)])
    assert eje.coverage_projected == pytest.approx(0.25)


def test_las_dos_coberturas_no_se_suman_ni_se_pisan():
    eje = _eje([(REAL, 0.5, 1.0), (PROJECTED, 0.5, 1.0)])
    assert eje.coverage_real == pytest.approx(0.5)
    assert eje.coverage_projected == pytest.approx(0.5)


def test_el_conteo_de_estados_declara_las_cuatro_claves():
    """Un eje sin proyecciones tiene que decir `projected: 0`, no omitir la clave: una clave
    ausente se lee como «no aplica» y no como «cero»."""
    eje = _eje([(REAL, 1.0, 1.0)])
    assert set(eje.state_counts) == {REAL, RUBRIC, PROJECTED, GAP}
    assert eje.state_counts[PROJECTED] == 0


def test_el_resumen_del_portafolio_tambien():
    reg = DataRegistry(generated_at="2026-09-04", axes=(_eje(_MIXTO),))
    resumen = reg.summary
    assert set(resumen["by_state"]) == {REAL, RUBRIC, PROJECTED, GAP}
    assert "coverage_projected_mean" in resumen
    assert resumen["coverage_real_mean"] == pytest.approx(_eje(_MIXTO).coverage_real)
