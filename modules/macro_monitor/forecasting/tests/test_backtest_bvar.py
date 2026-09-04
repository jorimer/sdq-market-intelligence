"""El backtest del BVAR: ventana expansiva, y λ₁ re-elegido en CADA corte.

Elegir λ₁ una vez sobre la muestra entera y reusarlo en cada pronóstico metería, en todos
ellos, información de trimestres que en ese momento no existían. El spec marca esa
contaminación como el riesgo principal del bloque, y no es visible en el resultado: un
backtest contaminado se ve mejor, no roto.
"""
import numpy as np
import pytest

from modules.macro_monitor.forecasting import backtest_bvar, bvar


def _serie(n=90, k=3, semilla=11):
    rng = np.random.default_rng(semilla)
    A = np.array([[0.5, 0.1, 0.0], [0.0, 0.6, 0.1], [0.1, 0.0, 0.4]])[:k, :k]
    Y = np.zeros((n, k))
    for t in range(1, n):
        Y[t] = A @ Y[t - 1] + rng.normal(0, 1, k)
    return Y


_NOMBRES = ("pib_real", "b", "c")


def _trimestres(n):
    out = []
    a, q = 2000, 1
    for _ in range(n):
        out.append(f"{a}-Q{q}")
        q += 1
        if q == 5:
            a, q = a + 1, 1
    return out


def test_devuelve_un_resultado_por_horizonte():
    Y = _serie()
    res = backtest_bvar.correr(Y, _NOMBRES, _trimestres(len(Y)), pasos=4, min_train=40)
    assert [r.h for r in res] == [1, 2, 3, 4]


def test_cada_horizonte_reporta_su_propio_n():
    """Promediar el error entre horizontes es engañar: un pronóstico a un trimestre no tiene
    el mismo error que a ocho."""
    res = backtest_bvar.correr(_serie(), _NOMBRES, _trimestres(90), pasos=4, min_train=40)
    assert all(r.n > 0 for r in res)
    assert res[0].n >= res[-1].n, "los horizontes largos no pueden tener MÁS casos"


def test_reporta_la_cobertura_de_LOS_DOS_niveles():
    res = backtest_bvar.correr(_serie(), _NOMBRES, _trimestres(90), pasos=2, min_train=40)
    for r in res:
        assert 0.0 <= r.cobertura_80 <= 1.0
        assert 0.0 <= r.cobertura_90 <= 1.0
        assert r.cobertura_90 >= r.cobertura_80, (
            "el intervalo del 90% no puede cubrir menos que el del 80%")


def test_el_random_walk_esta_siempre_al_lado():
    """Sin la referencia, un RMSE es un número sin escala."""
    res = backtest_bvar.correr(_serie(), _NOMBRES, _trimestres(90), pasos=2, min_train=40)
    assert all(r.rmse_random_walk > 0 for r in res)


def test_sin_muestra_no_inventa_resultado():
    assert backtest_bvar.correr(_serie(n=20), _NOMBRES, _trimestres(20), min_train=40) == []


def test_lambda1_se_reelige_en_cada_corte(monkeypatch):
    """Si se eligiera una sola vez, habría UNA llamada; con ventana expansiva hay una por
    corte, cada una con su propia ventana de entrenamiento."""
    llamadas = []
    original = bvar.elegir_lambda1

    def espia(Y, p=2, grilla=bvar.GRILLA_LAMBDA1):
        llamadas.append(len(Y))
        return original(Y, p, grilla)

    monkeypatch.setattr(bvar, "elegir_lambda1", espia)
    backtest_bvar.correr(_serie(n=60), _NOMBRES, _trimestres(60), pasos=2, min_train=40)
    assert len(llamadas) > 1, "λ₁ se eligió una sola vez para todos los cortes"
    assert llamadas == sorted(llamadas), "la ventana de entrenamiento no crece"
    assert len(set(llamadas)) == len(llamadas), "dos cortes usaron la misma ventana"
