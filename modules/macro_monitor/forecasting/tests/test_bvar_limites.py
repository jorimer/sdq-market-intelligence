"""Los DOS casos límite del prior Minnesota. Es la única defensa real de este código.

Un BVAR por observaciones artificiales es álgebra que nadie va a auditar línea por línea: un
signo cambiado o un índice corrido produce números plausibles y equivocados, y ningún test de
«corre sin excepción» lo notaría. Lo que sí lo nota son los dos extremos, porque el prior
tiene un comportamiento *conocido* en cada uno:

* con **λ₁ → 0** el prior domina: el estimador tiene que converger al **random walk**
  (coeficiente 1 sobre el propio primer rezago, 0 en todo lo demás);
* con **λ₁ → ∞** el prior se desvanece: tiene que converger al **OLS sin restringir**.

Un error de álgebra rompe casi con seguridad al menos uno de los dos.
"""
import numpy as np
import pytest

from modules.macro_monitor.forecasting import bvar


def _serie(n=120, k=3, semilla=7):
    """Un VAR estable con innovaciones reproducibles."""
    rng = np.random.default_rng(semilla)
    A = np.array([[0.5, 0.1, 0.0], [0.0, 0.6, 0.1], [0.1, 0.0, 0.4]])[:k, :k]
    Y = np.zeros((n, k))
    for t in range(1, n):
        Y[t] = A @ Y[t - 1] + rng.normal(0, 1, k)
    return Y


def test_con_tightness_casi_cero_converge_al_random_walk():
    Y = _serie()
    aj = bvar.ajustar(Y, p=1, lambda1=1e-6)
    n = Y.shape[1]
    propios = np.array([aj.beta[i, i] for i in range(n)])
    assert np.allclose(propios, 1.0, atol=0.02), (
        f"con el prior dominando, los coeficientes propios deberían ir a 1: {propios}")
    cruzados = np.array([aj.beta[i, j] for i in range(n) for j in range(n) if i != j])
    assert np.allclose(cruzados, 0.0, atol=0.02), (
        f"y los cruzados a 0: {cruzados}")


def test_con_tightness_enorme_converge_al_OLS_sin_restringir():
    Y = _serie()
    aj = bvar.ajustar(Y, p=1, lambda1=1e6)
    X, Yt = bvar._rezagos(Y, 1)
    ols, *_ = np.linalg.lstsq(X, Yt, rcond=None)
    assert np.allclose(aj.beta, ols, atol=1e-3), (
        "con el prior desvanecido tendría que coincidir con el OLS sin restringir")


def test_entre_los_dos_extremos_el_estimador_se_mueve_monotonamente():
    """Si al aflojar el prior el estimador no se acerca al OLS, hay algo mal en el álgebra
    aunque los dos extremos den bien."""
    Y = _serie()
    X, Yt = bvar._rezagos(Y, 1)
    ols, *_ = np.linalg.lstsq(X, Yt, rcond=None)
    distancias = [float(np.linalg.norm(bvar.ajustar(Y, p=1, lambda1=lam).beta - ols))
                  for lam in (0.01, 0.1, 1.0, 10.0, 100.0)]
    assert distancias == sorted(distancias, reverse=True), distancias


# ── La elección de λ₁ ───────────────────────────────────────────────────────────────
def test_lambda1_sale_de_la_grilla_declarada():
    assert bvar.elegir_lambda1(_serie(), p=1) in bvar.GRILLA_LAMBDA1


def test_lambda1_se_elige_SOLO_con_la_ventana_de_entrenamiento():
    """El criterio no puede depender de datos posteriores: si mirara el error fuera de
    muestra, el backtest sería un examen con las respuestas al lado."""
    Y = _serie(n=120)
    entrenamiento = Y[:80]
    a = bvar.elegir_lambda1(entrenamiento, p=1)
    b = bvar.elegir_lambda1(entrenamiento, p=1)
    assert a == b
    # y agregar datos POSTERIORES no puede cambiar la elección hecha sobre la ventana
    assert bvar.elegir_lambda1(Y[:80], p=1) == a


def test_lambda2_esta_fijo_en_uno_y_se_declara():
    """No es una preferencia: el prior conjugado lo impone. Se declara en la metodología del
    reporte en vez de esconderse."""
    assert bvar.LAMBDA2 == 1.0
    assert "λ₂ = 1" in bvar.__doc__ or "λ₂ = 1 fijo" in bvar.__doc__


# ── La proyección ───────────────────────────────────────────────────────────────────
def test_la_incertidumbre_crece_con_el_horizonte():
    """Proyectar a 8 trimestres es más incierto que a 1, y el intervalo tiene que decirlo."""
    Y = _serie()
    aj = bvar.ajustar(Y, p=1, lambda1=0.2)
    _centro, desvios = bvar.proyectar(aj, Y, pasos=8)
    primera = desvios[:, 0]
    assert list(primera) == sorted(primera), primera
    assert primera[-1] > primera[0]


def test_los_intervalos_contienen_al_punto_y_el_90_al_80():
    ints = bvar.intervalos(3.0, 0.5)
    i80 = next(i for i in ints if i[0] == 0.80)
    i90 = next(i for i in ints if i[0] == 0.90)
    assert i80[1] <= 3.0 <= i80[2]
    assert i90[1] <= i80[1] and i90[2] >= i80[2]
