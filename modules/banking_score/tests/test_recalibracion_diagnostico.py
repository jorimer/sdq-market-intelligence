"""El diagnóstico de la recalibración: que reconstruya el score VIEJO, no otro parecido.

Si las curvas previas están mal copiadas, la comparación 0,44 → 0,16 mide una diferencia
inventada y la conclusión —que decide si el arreglo es del score o del reporte— sale al revés.
Estos tests fijan las curvas contra los valores que la propia recalibración documentó.
"""
from types import SimpleNamespace

import pytest

from modules.banking_score.scoring.engine import (
    calc_cobertura_provisiones, calc_leverage, calc_solvencia, calc_tier1_ratio,
)
from modules.banking_score.validation.recalibracion import (
    _cobertura_previa, _leverage_previa, _solvencia_previa, _tier1_previa,
    solidez_previa,
)


def _dato(**campos):
    """Una fila de `banking_data` con lo justo para los cinco indicadores de solidez."""
    base = dict(
        solvencia_pct=None, tier1_pct=None, cobertura_pct=None,
        patrimonio_tecnico=None, apr=None, contingentes=None, riesgo_mercado=None,
        capital_primario=None, capital_tier1=None, exposicion_total=None,
        provisiones=None, cartera_vencida_90d=None, activos_totales=None,
    )
    base.update(campos)
    return SimpleNamespace(**base)


# ── Las curvas previas, contra los hechos que las jubilaron ───────

# Entre el techo viejo (15%) y el nuevo (31,3%): el tramo donde la curva vieja ya
# saturaba y la de hoy todavía separa. Arriba de 31,3 las dos dan 100 y la
# comparación no diría nada.
@pytest.mark.parametrize("crudo", [15.0, 20.0, 25.0, 31.0])
def test_solvencia_previa_saturaba_donde_la_de_hoy_discrimina(crudo):
    """El techo viejo era 15% de solvencia: del 15 para arriba, todos 100/100.

    Es el hecho que motivó la recalibración —«un banco que llegaba a 15% sacaba lo mismo que
    uno con 31%»— y el que la reconstrucción tiene que reproducir para ser comparable.
    """
    assert _solvencia_previa(crudo) == 100.0
    assert calc_solvencia(_dato(solvencia_pct=crudo))["score"] < 100.0


def test_la_curva_de_hoy_pone_el_minimo_regulatorio_en_50():
    """10% es el mínimo de solvencia en RD: cumplirlo vale 50, no 100."""
    assert calc_solvencia(_dato(solvencia_pct=10.0))["score"] == pytest.approx(50.0, abs=0.5)
    # Con la curva vieja, cumplir apenas el mínimo ya valía dos tercios del puntaje.
    assert _solvencia_previa(10.0) == pytest.approx(66.67, abs=0.05)


def test_tier1_previa_reproduce_el_piso_duro_en_45():
    """La curva vieja daba 0 por debajo de 4,5% y saturaba en 8,5%."""
    assert _tier1_previa(4.4) == 0.0
    assert _tier1_previa(8.5) == 100.0
    assert _tier1_previa(6.5) == pytest.approx(50.0, abs=0.01)
    assert calc_tier1_ratio(_dato(tier1_pct=8.5))["score"] < 100.0


def test_leverage_y_cobertura_previas_saturan_en_sus_techos_viejos():
    assert _leverage_previa(6.0) == 100.0
    assert _cobertura_previa(100.0) == 100.0
    assert calc_leverage(_dato(capital_tier1=6.0, exposicion_total=100.0))["score"] < 100.0
    assert calc_cobertura_provisiones(_dato(cobertura_pct=100.0))["score"] == pytest.approx(
        50.0, abs=0.5)


# ── El dato ausente, que es la otra mitad del cambio ──────────────

def test_el_dato_ausente_puntuaba_cero_en_la_solidez_vieja():
    """Sin ningún crudo, la solidez vieja da 0: `_safe_div` devolvía 0.0 y la ausencia
    puntuaba como el peor valor posible. Reproducirlo es el punto — es el score que
    produjo el 0,44, no una versión mejorada de él."""
    assert solidez_previa(_dato()) == 0.0


def test_la_solidez_vieja_promedia_los_cinco_indicadores():
    """Promedio simple: el motor viejo no declaraba indicadores no disponibles."""
    d = _dato(solvencia_pct=20.0, tier1_pct=10.0, cobertura_pct=150.0,
              capital_tier1=10.0, exposicion_total=100.0,
              patrimonio_tecnico=12.0, activos_totales=100.0)
    # solvencia 100 · tier1 100 · leverage 100 · cobertura 100 · patrimonio 100 → 100
    assert solidez_previa(d) == 100.0
    assert d.solvencia_pct == 20.0  # el diagnóstico no muta la fila


# ── El orquestador, sin panel ─────────────────────────────────────

def test_sin_panel_lo_declara_en_vez_de_devolver_un_cero():
    from modules.banking_score.validation import recalibracion

    class _DBVacia:
        def query(self, *_a, **_k):
            return self

        def filter(self, *_a, **_k):
            return self

        def all(self):
            return []

    salida = recalibracion.comparar_recalibracion(_DBVacia())
    assert salida["ok"] is False
    assert "sin panel" in salida["motivo"]
