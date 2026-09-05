"""El gate de admisión: una proyección sin backtest no ancla nada.

`projection_is_admissible` devuelve `(admisible, motivo)`. El motivo NO se descarta: alimenta
la nota de la brecha cuando la proyección se degrada, para que el informe diga *por qué* no se
estimó. Una proyección que no pasa no es una proyección mala — es un `GAP`.

Hay un caso por condición de rechazo, porque un gate con una condición muerta se ve idéntico
a uno completo hasta el día que deja pasar algo.
"""
import math

import pytest

from shared.registry.projection import MIN_OOS, projection_is_admissible
from shared.registry.signals import ProjectionMeta
from shared.data.medida_de_pronostico import DLOG_PCT


def _meta(**cambios):
    base = dict(
        model_id="bridge_imae_pib.m2.v1",
        target_series="bcrd.xls.pib_2018.serie_original_indice",
        horizon="2026-Q4",
        as_of="2026-08-31",
        revision=0,
        point=3.9,
        intervals=((0.80, 3.1, 4.7), (0.90, 2.6, 5.2)),
        measure=DLOG_PCT,
        backtest_id="bridge_imae_pib.m2.v1|bcrd.xls.pib_2018.serie_original_indice|2026-Q4",
        oos_error=0.62,
        error_metric="rmse",
        n_oos=16,
        n_oos_overlapping=True,
        interval_coverage=((0.80, 0.78, 16), (0.90, 0.88, 16)),
    )
    base.update(cambios)
    return ProjectionMeta(**base)


def test_una_proyeccion_completa_pasa():
    ok, motivo = projection_is_admissible(_meta())
    assert ok, motivo
    assert motivo == ""


@pytest.mark.parametrize("meta,fragmento", [
    (None, "no hay proyección"),
    (_meta(model_id=""), "model_id"),
    (_meta(target_series=""), "target_series"),
    (_meta(backtest_id=""), "backtest_id"),
    (_meta(intervals=()), "sin intervalos"),
    (_meta(intervals=((1.2, 3.1, 4.7),)), "fuera de (0, 1)"),
    (_meta(intervals=((0.80, 3.1, 4.7), (0.80, 2.6, 5.2))), "duplicado"),
    (_meta(intervals=((0.80, 4.1, 4.7),)), "no contiene al punto"),
    (_meta(intervals=((0.80, 2.6, 5.2), (0.90, 3.1, 4.7))), "anidado"),
    (_meta(n_oos=MIN_OOS - 1), "observaciones fuera de muestra"),
    (_meta(n_oos_overlapping=None), "solapamiento"),
    (_meta(oos_error=float("nan")), "error"),
    (_meta(oos_error=float("inf")), "error"),
    (_meta(as_of="2027-03-01"), "posterior"),
    (_meta(interval_coverage=((0.95, 0.9, 16),)), "calibración"),
])
def test_cada_condicion_de_rechazo_rechaza(meta, fragmento):
    ok, motivo = projection_is_admissible(meta)
    assert not ok, f"pasó una proyección que debía rechazarse ({fragmento})"
    assert fragmento.lower() in motivo.lower(), (
        f"el motivo no nombra la causa: esperaba «{fragmento}», dijo «{motivo}»")


def test_el_motivo_nunca_viene_vacio_cuando_rechaza():
    ok, motivo = projection_is_admissible(None)
    assert not ok and motivo, "rechazó sin decir por qué: el informe se queda sin la razón"


def test_un_horizonte_relativo_no_se_puede_contrastar_contra_as_of():
    """`+4T` no resuelve a un período absoluto: la condición no aplica, y no aplicar no es
    fallar. Lo que no se puede verificar no se inventa."""
    ok, motivo = projection_is_admissible(_meta(horizon="+4T"))
    assert ok, motivo


def test_min_oos_es_exactamente_el_piso():
    assert projection_is_admissible(_meta(n_oos=MIN_OOS))[0]
    assert not projection_is_admissible(_meta(n_oos=MIN_OOS - 1))[0]


def test_min_oos_vale_doce():
    """Recalibrable por PR, pero el número tiene que estar a la vista y no en una intuición."""
    assert MIN_OOS == 12


def test_el_error_no_finito_no_pasa_por_ser_un_numero():
    assert not math.isfinite(float("nan"))
    assert not projection_is_admissible(_meta(oos_error=float("nan")))[0]
