"""El SEGUNDO motor: P/B explicado por fundamentales, sobre el panel LATAM.

    P/B = f(ROE, crecimiento, volatilidad de resultados, tamaño, calidad de cartera)

**Existe para CONTRASTAR, no para promediar.** El Excess Return dice cuánto vale una entidad
según lo que gana sobre su costo de capital; esta regresión dice a cuánto cotizan bancos
comparables con fundamentales parecidos. Son dos preguntas distintas con dos fuentes de error
distintas, y cuando divergen **la divergencia es información**: significa que el mercado
comparable está pagando algo que el flujo no explica, o al revés. Promediarlos hasta que
parezca una sola respuesta borra exactamente eso.

**El error fuera de muestra manda sobre el `R²`.** Un `R²` alto sobre el panel entero solo
dice que el modelo describe el panel; lo que interesa es si predice el P/B de un banco que no
vio. Se reporta con validación cruzada dejando-uno-afuera, que con paneles chicos es la que
usa toda la muestra sin partirla en dos trozos aún más chicos.

**Sin panel suficiente, no publica.** Ver el gate en `panel/latam_comparables.py`: con menos
de diez observaciones por predictor, el `R²` sube por memorización. Un segundo motor mal
estimado no da una segunda opinión — da una coincidencia inventada.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import List, Optional, Sequence, Tuple

import numpy as np

from modules.valuation.panel.latam_comparables import (
    PREDICTORES,
    Comparable,
    estado,
    matriz,
)


class PanelInsuficienteError(ValueError):
    """No hay bancos suficientes para estimar. Se consulta ANTES de regresar."""


@dataclass(frozen=True)
class Ajuste:
    """La regresión, con lo que hace falta para juzgarla — no solo para usarla."""

    intercepto: float
    coeficientes: Tuple[float, ...]
    nombres: Tuple[str, ...]
    n: int
    r2: float
    #: Error fuera de muestra por validación cruzada dejando-uno-afuera. Es el número que
    #: manda: el R² describe el panel, esto estima lo que pasa con un banco nuevo.
    rmse_oos: float
    #: RMSE dentro de muestra, al lado del de afuera. La BRECHA entre los dos es la medida
    #: de sobreajuste, y esconderla dejaría al R² contando la mitad de la historia.
    rmse_in: float

    @property
    def sobreajuste(self) -> float:
        return round(self.rmse_oos - self.rmse_in, 6)


def _ols(X: np.ndarray, y: np.ndarray) -> np.ndarray:
    """Mínimos cuadrados con intercepto, por `lstsq` — estable con colinealidad moderada."""
    A = np.column_stack([np.ones(len(X)), X])
    beta, *_ = np.linalg.lstsq(A, y, rcond=None)
    return beta


def _predecir(beta: np.ndarray, X: np.ndarray) -> np.ndarray:
    return np.column_stack([np.ones(len(X)), X]) @ beta


def ajustar(panel: Sequence[Comparable]) -> Ajuste:
    """Estima el modelo. Lanza si el panel no alcanza."""
    est = estado(panel)
    if not est.suficiente:
        raise PanelInsuficienteError(est.motivo)

    Xl, yl = matriz(panel)
    X, y = np.array(Xl, dtype=float), np.array(yl, dtype=float)
    beta = _ols(X, y)
    pred = _predecir(beta, X)
    resid = y - pred
    ss_res = float((resid ** 2).sum())
    ss_tot = float(((y - y.mean()) ** 2).sum())
    r2 = 1.0 - ss_res / ss_tot if ss_tot else 0.0
    rmse_in = float(np.sqrt((resid ** 2).mean()))

    # Dejando-uno-afuera: con paneles chicos, partir en dos deja trozos que no estiman nada.
    errores: List[float] = []
    for i in range(len(y)):
        mask = np.ones(len(y), dtype=bool)
        mask[i] = False
        b = _ols(X[mask], y[mask])
        errores.append(float(y[i] - _predecir(b, X[i:i + 1])[0]))
    rmse_oos = float(np.sqrt(np.mean(np.array(errores) ** 2)))

    return Ajuste(intercepto=float(beta[0]), coeficientes=tuple(float(b) for b in beta[1:]),
                  nombres=PREDICTORES, n=len(y), r2=round(r2, 6),
                  rmse_oos=round(rmse_oos, 6), rmse_in=round(rmse_in, 6))


def pb_predicho(aj: Ajuste, *, roe_pct: float, crecimiento_pct: float,
                volatilidad_roe: float, log_activos: float,
                calidad_cartera_pct: float) -> float:
    """El P/B que el panel implica para una entidad con estos fundamentales."""
    x = np.array([roe_pct, crecimiento_pct, volatilidad_roe, log_activos,
                  calidad_cartera_pct], dtype=float)
    return float(aj.intercepto + float(np.array(aj.coeficientes) @ x))


# ── el cruce con el otro motor ──────────────────────────────────────────────────────

#: A partir de esta distancia relativa entre los dos motores, la divergencia se REPORTA como
#: hallazgo en vez de tratarse como ruido. Un cuarto: por debajo, la diferencia cabe dentro
#: del error de estimación de cualquiera de los dos.
UMBRAL_DE_DIVERGENCIA = 0.25


@dataclass(frozen=True)
class Contraste:
    """Los dos motores, lado a lado. NUNCA promediados."""

    pb_excess_return: float
    pb_regresion: float
    divergencia_relativa: float
    divergen: bool
    lectura: str

    @property
    def rango(self) -> Tuple[float, float]:
        """Un rango con los dos, no un punto entre los dos."""
        return (min(self.pb_excess_return, self.pb_regresion),
                max(self.pb_excess_return, self.pb_regresion))


def contrastar(pb_excess_return: float, pb_regresion: float) -> Contraste:
    """Cruza los dos motores. Si divergen, la divergencia ES el resultado.

    No se promedia. Promediar dos estimaciones que se contradicen produce un número que
    ninguno de los dos modelos sostiene, y que además esconde que se contradicen.
    """
    base = max(abs(pb_excess_return), abs(pb_regresion), 1e-9)
    div = abs(pb_excess_return - pb_regresion) / base
    divergen = div >= UMBRAL_DE_DIVERGENCIA
    if not divergen:
        lectura = (
            f"Los dos motores coinciden dentro de {UMBRAL_DE_DIVERGENCIA:.0%}: el valor que "
            "surge del flujo y el que implican los comparables cuentan la misma historia.")
    elif pb_regresion > pb_excess_return:
        lectura = (
            f"Divergen {div:.0%}: **los comparables pagan más de lo que el flujo explica**. "
            "El mercado le reconoce a bancos parecidos algo que el Excess Return no captura "
            "—expectativas de crecimiento, valor de franquicia, o simplemente una prima que "
            "no se sostiene—. La diferencia es el hallazgo, no un promedio a tomar.")
    else:
        lectura = (
            f"Divergen {div:.0%}: **el flujo justifica más de lo que los comparables pagan**. "
            "O la entidad tiene una rentabilidad que el mercado comparable no está premiando, "
            "o el supuesto de ROE sostenido es demasiado optimista. La diferencia es el "
            "hallazgo, no un promedio a tomar.")
    return Contraste(pb_excess_return=pb_excess_return, pb_regresion=pb_regresion,
                     divergencia_relativa=round(div, 6), divergen=divergen, lectura=lectura)
