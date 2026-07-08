"""Función de reacción de política monetaria (regla tipo Taylor, interpretable).

Estima por OLS (``sklearn.LinearRegression``) el nivel de la TPM como función de la brecha
de inflación, la brecha de producto y la TPM rezagada (término de suavizamiento, estándar
en las estimaciones de reglas de Taylor). Devuelve la tasa IMPLÍCITA y el SESGO (implícita −
vigente): sesgo positivo ⇒ la regla pide una postura más restrictiva; negativo ⇒ más laxa.

Se serializa como coeficientes (dict), no como pickle: la predicción es un producto punto,
así que el modelo persistido es legible y auditable.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Optional

import numpy as np

from modules.macro_monitor.tpm_modeling.dataset import PanelRow
from modules.macro_monitor.tpm_modeling.features import TAYLOR_FEATURES


@dataclass
class ReactionFunction:
    """Coeficientes de la regla + calidad de ajuste. ``predict`` = producto punto."""

    coefficients: Dict[str, float]
    intercept: float
    r2: float
    n_obs: int
    features: List[str]

    def predict(self, feats: Dict[str, Optional[float]]) -> Optional[float]:
        """Tasa implícita para un vector de features (None si falta alguna Taylor)."""
        acc = self.intercept
        for name in self.features:
            v = feats.get(name)
            if v is None:
                return None
            acc += self.coefficients[name] * float(v)
        return float(acc)

    def bias(self, feats: Dict[str, Optional[float]], current_tpm: Optional[float]) -> Optional[float]:
        """Sesgo = tasa implícita − TPM vigente (puntos porcentuales)."""
        implied = self.predict(feats)
        if implied is None or current_tpm is None:
            return None
        return float(implied - current_tpm)

    def to_dict(self) -> Dict:
        return {
            "coefficients": self.coefficients, "intercept": self.intercept,
            "r2": self.r2, "n_obs": self.n_obs, "features": self.features,
        }

    @classmethod
    def from_dict(cls, d: Dict) -> "ReactionFunction":
        return cls(
            coefficients=dict(d["coefficients"]), intercept=float(d["intercept"]),
            r2=float(d["r2"]), n_obs=int(d["n_obs"]), features=list(d["features"]),
        )


def _matrix(rows: List[PanelRow], feature_names: List[str]):
    """(X, y) de las filas con target de nivel y todas las features Taylor presentes."""
    X, y = [], []
    for r in rows:
        if r.tpm_level is None:
            continue
        vec = [r.features.get(n) for n in feature_names]
        if any(v is None for v in vec):
            continue
        X.append([float(v) for v in vec])
        y.append(float(r.tpm_level))
    return np.asarray(X, dtype=float), np.asarray(y, dtype=float)


def fit_reaction_function(rows: List[PanelRow], feature_names: List[str] = TAYLOR_FEATURES) -> ReactionFunction:
    """Ajusta la regla de Taylor sobre el panel completo (para servir la tasa implícita).

    El backtest usa su propio ajuste expanding-window; este ``fit`` es el modelo "final"
    entrenado con toda la historia, para el forecast en producción.
    """
    from sklearn.linear_model import LinearRegression

    X, y = _matrix(rows, feature_names)
    if len(y) < len(feature_names) + 2:
        raise ValueError(
            f"Datos insuficientes para estimar la regla de Taylor: {len(y)} observaciones con "
            f"nivel y features completas.")
    model = LinearRegression()
    model.fit(X, y)
    return ReactionFunction(
        coefficients={n: float(c) for n, c in zip(feature_names, model.coef_)},
        intercept=float(model.intercept_),
        r2=float(model.score(X, y)),
        n_obs=int(len(y)),
        features=list(feature_names),
    )
