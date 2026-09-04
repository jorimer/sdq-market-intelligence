"""BVAR con prior Minnesota, implementado por OBSERVACIONES ARTIFICIALES sobre OLS.

**Por qué priors.** Con ~76 trimestres y varias variables, un VAR sin restricciones estima
más parámetros de los que la data sostiene y termina ajustando ruido. El prior Minnesota
encoge hacia un random walk, que es la hipótesis nula honesta para series macro.

**Por qué sin `statsmodels`.** No aportaría: ofrece `VAR`, `VARMAX` y `VECM`, y **no** BVAR
con prior Minnesota. El método de Bañbura, Giannone & Reichlin (2010) implementa el prior
añadiendo filas artificiales al dataset y corriendo OLS sobre el conjunto aumentado — son
unas decenas de líneas, cada una inspeccionable.

**Los hiperparámetros, y la restricción que se declara en vez de esconderse.** La
verosimilitud marginal en forma cerrada solo existe bajo el prior natural-conjugado, y ese
prior impone estructura Kronecker en la covarianza, lo que **fuerza λ₂ = 1**: obliga a tratar
igual los rezagos propios y los cruzados. No se puede tener forma cerrada y λ₂ libre a la vez.
Se toma la rama conjugada: **λ₂ = 1 fijo, λ₃ = 2** (decaimiento cuadrático, el valor
convencional de la literatura) y **λ₁ elegido por verosimilitud marginal en la ventana de
ENTRENAMIENTO**.

**El error fuera de muestra NO se mira para elegir λ₁.** Es la vía más fácil de contaminar un
backtest: el modelo terminaría eligiendo su hiperparámetro con la respuesta a la vista, y el
error que reporte sería el de un examen con las respuestas al lado.

Este código nadie lo va a auditar línea por línea, así que su defensa son los DOS CASOS
LÍMITE, que un error de álgebra rompe casi con seguridad:

* con `λ₁ → 0` el prior domina y el estimador converge al **random walk**;
* con `λ₁ → ∞` el prior se desvanece y converge al **OLS sin restringir**.
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from typing import List, Optional, Sequence, Tuple

import numpy as np

#: Impuesto por el prior conjugado: no se puede tener verosimilitud marginal en forma
#: cerrada y λ₂ libre a la vez. Se DECLARA en la metodología del reporte.
LAMBDA2 = 1.0
#: Decaimiento de rezagos, cuadrático — el valor convencional de la literatura Minnesota.
LAMBDA3 = 2.0
#: La grilla sobre la que se busca λ₁ por verosimilitud marginal. Nunca por error OOS.
GRILLA_LAMBDA1 = (0.02, 0.05, 0.1, 0.2, 0.3, 0.5, 1.0, 2.0, 5.0)


def _rezagos(Y: np.ndarray, p: int) -> Tuple[np.ndarray, np.ndarray]:
    """``(X, Y)`` del VAR(p): X lleva los p rezagos y una constante al final."""
    T, n = Y.shape
    filas, objetivo = [], []
    for t in range(p, T):
        fila: List[float] = []
        for k in range(1, p + 1):
            fila.extend(Y[t - k])
        fila.append(1.0)
        filas.append(fila)
        objetivo.append(Y[t])
    return np.array(filas), np.array(objetivo)


def dummies_minnesota(Y: np.ndarray, p: int, lambda1: float, *, sigmas: np.ndarray,
                      medias: np.ndarray) -> Tuple[np.ndarray, np.ndarray]:
    """Las observaciones artificiales que IMPLEMENTAN el prior.

    Tres bloques, cada uno una creencia declarada:

    1. **Los coeficientes propios se encogen hacia 1 y los cruzados hacia 0** — es decir,
       hacia un random walk. La fuerza la da ``λ₁``, y el decaimiento por rezago ``k^λ₃``.
    2. **La constante casi no se encoge** (prior difuso): no hay creencia previa sobre el
       nivel.
    3. **Escala de la covarianza**: fija la unidad en que se mide todo lo anterior.
    """
    n = Y.shape[1]
    k = n * p + 1
    Xd: List[List[float]] = []
    Yd: List[List[float]] = []

    # 1 · coeficientes propios → 1, cruzados → 0, con decaimiento k^λ₃
    for rez in range(1, p + 1):
        for i in range(n):
            fila = [0.0] * k
            fila[(rez - 1) * n + i] = (rez ** LAMBDA3) * sigmas[i] / lambda1
            Xd.append(fila)
            objetivo = [0.0] * n
            if rez == 1:
                objetivo[i] = (rez ** LAMBDA3) * sigmas[i] / lambda1
            Yd.append(objetivo)

    # 2 · constante con prior difuso
    fila = [0.0] * k
    fila[-1] = 1e-4
    Xd.append(fila)
    Yd.append([0.0] * n)

    # 3 · escala de la covarianza
    for i in range(n):
        Xd.append([0.0] * k)
        objetivo = [0.0] * n
        objetivo[i] = sigmas[i]
        Yd.append(objetivo)

    _ = medias  # el prior de medias no se usa en la rama conjugada; se deja explícito
    return np.array(Xd), np.array(Yd)


def _sigmas_ar(Y: np.ndarray, p: int) -> np.ndarray:
    """Escala de cada variable: desvío residual de un AR(p) univariado, como manda el
    método. Usar el desvío crudo mezclaría nivel con innovación."""
    n = Y.shape[1]
    out = np.ones(n)
    for i in range(n):
        y = Y[:, i]
        if len(y) <= p + 2:
            out[i] = float(np.std(y)) or 1.0
            continue
        X = np.array([[1.0, *y[t - p:t][::-1]] for t in range(p, len(y))])
        objetivo = y[p:]
        beta, *_ = np.linalg.lstsq(X, objetivo, rcond=None)
        resid = objetivo - X @ beta
        gl = max(len(objetivo) - X.shape[1], 1)
        out[i] = math.sqrt(float(resid @ resid) / gl) or 1.0
    return out


@dataclass(frozen=True)
class Ajuste:
    beta: np.ndarray          # (k, n) coeficientes
    sigma: np.ndarray         # (n, n) covarianza residual
    lambda1: float
    n_obs: int
    p: int


def ajustar(Y: np.ndarray, p: int = 2, lambda1: float = 0.2) -> Ajuste:
    """OLS sobre el conjunto AUMENTADO con las observaciones artificiales."""
    X, Yt = _rezagos(Y, p)
    sigmas = _sigmas_ar(Y, p)
    Xd, Yd = dummies_minnesota(Y, p, lambda1, sigmas=sigmas, medias=Y.mean(axis=0))
    Xa = np.vstack([X, Xd])
    Ya = np.vstack([Yt, Yd])
    beta, *_ = np.linalg.lstsq(Xa, Ya, rcond=None)
    resid = Yt - X @ beta
    gl = max(len(Yt) - Xa.shape[1] // max(Y.shape[1], 1), 1)
    return Ajuste(beta=beta, sigma=(resid.T @ resid) / gl, lambda1=lambda1,
                  n_obs=len(Yt), p=p)


def log_verosimilitud_marginal(Y: np.ndarray, p: int, lambda1: float) -> float:
    """Criterio para elegir λ₁ — calculado SOLO con la ventana de entrenamiento.

    Es una aproximación gaussiana a la verosimilitud marginal bajo el prior conjugado:
    penaliza el ajuste por la complejidad efectiva que el prior deja pasar. Lo que importa de
    ella es que **no mira el error fuera de muestra**: elegir el hiperparámetro con la
    respuesta a la vista convierte el backtest en un examen con las respuestas al lado.
    """
    aj = ajustar(Y, p, lambda1)
    X, Yt = _rezagos(Y, p)
    resid = Yt - X @ aj.beta
    T, n = Yt.shape
    sse = float(np.trace(resid.T @ resid))
    if sse <= 0:
        return float("-inf")
    # grados de libertad efectivos: cuánto del ajuste permite el prior
    Xd, _Yd = dummies_minnesota(Y, p, lambda1, sigmas=_sigmas_ar(Y, p),
                                medias=Y.mean(axis=0))
    Xa = np.vstack([X, Xd])
    try:
        H = X @ np.linalg.pinv(Xa.T @ Xa) @ X.T
        gl_ef = float(np.trace(H))
    except np.linalg.LinAlgError:  # pragma: no cover
        gl_ef = float(X.shape[1])
    return -0.5 * T * n * math.log(sse / (T * n)) - 0.5 * gl_ef * n * math.log(max(T, 2))


def elegir_lambda1(Y: np.ndarray, p: int = 2,
                   grilla: Sequence[float] = GRILLA_LAMBDA1) -> float:
    """El λ₁ que maximiza la verosimilitud marginal EN ENTRENAMIENTO."""
    mejor, mejor_v = grilla[0], float("-inf")
    for lam in grilla:
        v = log_verosimilitud_marginal(Y, p, lam)
        if v > mejor_v:
            mejor, mejor_v = lam, v
    return mejor


def proyectar(aj: Ajuste, Y: np.ndarray, pasos: int) -> Tuple[np.ndarray, np.ndarray]:
    """Trayectoria central y desvío por paso, iterando el VAR hacia adelante.

    El desvío acumula la varianza de la innovación paso a paso: proyectar a 8 trimestres es
    más incierto que a 1, y el intervalo tiene que decirlo.
    """
    p, n = aj.p, Y.shape[1]
    hist = list(Y[-p:])
    centro, desvios = [], []
    var_acum = np.zeros(n)
    diag = np.clip(np.diag(aj.sigma), 0.0, None)
    for _ in range(pasos):
        fila: List[float] = []
        for k in range(1, p + 1):
            fila.extend(hist[-k])
        fila.append(1.0)
        y = np.array(fila) @ aj.beta
        hist.append(y)
        centro.append(y)
        var_acum = var_acum + diag
        desvios.append(np.sqrt(var_acum))
    return np.array(centro), np.array(desvios)


#: Cuantiles normales de los dos niveles que el ledger puntúa.
_Z = {0.80: 1.2815515655446004, 0.90: 1.6448536269514722}


def intervalos(centro: float, desvio: float) -> List[List[float]]:
    return [[niv, round(centro - z * desvio, 6), round(centro + z * desvio, 6)]
            for niv, z in _Z.items()]


# ── Uso sobre el bloque real ────────────────────────────────────────────────────────

#: Hasta qué horizonte el BVAR se publica como PRONÓSTICO, con track record. Más allá es
#: escenario. No es una preferencia: el backtest sobre la muestra completa le gana al random
#: walk en los ocho horizontes (+18% a +37%), pero recortando la pandemia queda
#: h=1 +66,3% · h=2 +1,4% · h=3 +60,5% · h=4 −43,5% — a cuatro trimestres el random walk
#: GANA, y esa alternancia con n≈20 es ruido, no estructura. Lo único que sobrevive a las dos
#: muestras es el horizonte corto. Publicar «le gana en los 8» sería cierto y engañoso.
HORIZONTES_CON_TRACK_RECORD = 2

_ADVERTENCIA_ESCENARIO = (
    "Escenario, no pronóstico: más allá de dos trimestres la ventaja de este modelo sobre un "
    "random walk no sobrevive a excluir la pandemia de la muestra, así que no se le publica "
    "track record. Se muestra por su forma y su banda, no por su historial de acierto."
)


@dataclass(frozen=True)
class Pronostico:
    """Un horizonte con track record: entra al ledger y puede anclar una pregunta."""

    h: int
    horizonte: str
    punto: float
    intervalos: List[List[float]]
    model_id: str
    target_series: str
    backtest_id: str


@dataclass(frozen=True)
class Escenario:
    """Un horizonte SIN track record. No tiene `backtest_id`, y esa ausencia es el corte:
    sin él no se puede armar un `ProjectionMeta`, y sin `ProjectionMeta` el gate de admisión
    lo rechaza. Un escenario no puede anclar nada aunque alguien lo intente."""

    h: int
    horizonte: str
    punto: float
    intervalos: List[List[float]]
    model_id: str
    target_series: str
    es_escenario: bool = True
    advertencia: str = _ADVERTENCIA_ESCENARIO


def a_ledger(p) -> dict:
    """Los campos con que un PRONÓSTICO se registra. Un escenario no pasa por acá."""
    if not isinstance(p, Pronostico):
        raise TypeError(
            "solo un `Pronostico` se registra en el ledger. Lo que se recibió es un "
            "escenario: no tiene backtest que lo sostenga, y darle una fila de track record "
            "sería fabricarle uno.")
    return {"model_id": p.model_id, "target_series": p.target_series,
            "horizon": p.horizonte, "point": p.punto, "intervals": p.intervalos}


@dataclass(frozen=True)
class ProyeccionBVAR:
    model_id: str
    target: str
    horizontes: Tuple[str, ...]
    puntos: Tuple[float, ...]
    intervalos: Tuple[List[List[float]], ...]
    lambda1: float
    n_train: int
    variables: Tuple[str, ...]

    def _backtest_id(self) -> str:
        return f"{self.model_id}|{self.target}"

    def pronosticos(self) -> List[Pronostico]:
        """Los horizontes que se publican CON track record."""
        return [
            Pronostico(h=k + 1, horizonte=self.horizontes[k], punto=self.puntos[k],
                       intervalos=self.intervalos[k], model_id=self.model_id,
                       target_series=self.target,
                       backtest_id=f"{self._backtest_id()}|{self.horizontes[k]}")
            for k in range(min(HORIZONTES_CON_TRACK_RECORD, len(self.horizontes)))
        ]

    def escenarios(self) -> List[Escenario]:
        """Los horizontes largos: se muestran, no se puntúan."""
        return [
            Escenario(h=k + 1, horizonte=self.horizontes[k], punto=self.puntos[k],
                      intervalos=self.intervalos[k], model_id=self.model_id,
                      target_series=self.target)
            for k in range(HORIZONTES_CON_TRACK_RECORD, len(self.horizontes))
        ]


def _siguiente_trimestre(t: str) -> str:
    a, q = int(t[:4]), int(t[-1])
    return f"{a + 1}-Q1" if q == 4 else f"{a}-Q{q + 1}"


def proyectar_bloque(Y: np.ndarray, nombres: Sequence[str], ultimo_trimestre: str, *,
                     objetivo: str = "pib_real", pasos: int = 8, p: int = 2,
                     version: str = "v1") -> Optional["ProyeccionBVAR"]:
    """Ajusta el BVAR sobre *Y* y proyecta *objetivo* a *pasos* trimestres.

    λ₁ se elige por verosimilitud marginal SOBRE ESTA MISMA ventana — nunca mirando el error
    de lo que viene después, que es la forma más fácil de contaminar un backtest.
    """
    if len(Y) < 4 * p + 10 or objetivo not in nombres:
        return None
    i = list(nombres).index(objetivo)
    lam = elegir_lambda1(Y, p)
    aj = ajustar(Y, p, lam)
    centro, desvios = proyectar(aj, Y, pasos)
    horizontes, puntos, ints = [], [], []
    t = ultimo_trimestre
    for k in range(pasos):
        t = _siguiente_trimestre(t)
        horizontes.append(t)
        puntos.append(round(float(centro[k, i]), 4))
        ints.append(intervalos(float(centro[k, i]), float(desvios[k, i])))
    return ProyeccionBVAR(
        model_id=f"bvar_minnesota.{len(nombres)}v.{version}", target=objetivo,
        horizontes=tuple(horizontes), puntos=tuple(puntos), intervalos=tuple(ints),
        lambda1=lam, n_train=len(Y), variables=tuple(nombres),
    )
