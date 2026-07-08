"""Transformaciones puras de las series macro → vector de features del modelo de TPM.

Sin acceso a base de datos ni a red: recibe valores crudos point-in-time (los arma
:mod:`dataset`) y produce las variables interpretables de la función de reacción y del
clasificador. El HP-filter se implementa con ``scipy`` (NO statsmodels, que no está en
requirements) y se aplica SIEMPRE sobre la historia truncada a la fecha de la reunión
para no introducir look-ahead en la tendencia (brecha de producto one-sided).
"""
from __future__ import annotations

from typing import List, Optional

import numpy as np

# Meta de inflación del BCRD (shared/doctrine/macro_sector.yaml: favorable_at 4.0, banda ±1).
INFLATION_TARGET = 4.0

# λ del HP-filter para datos MENSUALES. Ravn-Uhlig sugiere ~129600; usamos ese valor
# estándar para actividad mensual (statsmodels usa 1600 para trimestral).
HP_LAMBDA_MONTHLY = 129_600.0

# Orden canónico del vector de features (regla + clasificador comparten base). El
# clasificador añade señales de cambio; la regla usa el subconjunto Taylor.
FEATURE_NAMES: List[str] = [
    "inflation_gap",   # inflación interanual − meta (4%)
    "output_gap",      # brecha de producto (HP one-sided sobre log del índice IMAE), %
    "real_rate",       # TPM vigente − inflación interanual (tasa real ex-post)
    "tpm_lag",         # nivel de la TPM de la decisión previa
    "fx_yoy",          # depreciación interanual del tipo de cambio de venta, %
    "reserves_yoy",    # variación interanual de reservas brutas, %
    "m1_yoy",          # variación interanual de M1, %
]

# Subconjunto que entra en la regla de reacción (Taylor con suavizamiento).
TAYLOR_FEATURES: List[str] = ["inflation_gap", "output_gap", "tpm_lag"]


def hp_filter(y: np.ndarray, lam: float = HP_LAMBDA_MONTHLY) -> np.ndarray:
    """Componente de tendencia del filtro Hodrick-Prescott (forma cerrada, scipy-free).

    Resuelve ``(I + λ D'D) τ = y`` donde ``D`` es el operador de segundas diferencias.
    Devuelve la tendencia ``τ``; el ciclo es ``y − τ``. Requiere ``len(y) >= 3``; con
    menos puntos devuelve ``y`` sin filtrar (no hay curvatura que penalizar).
    """
    y = np.asarray(y, dtype=float)
    n = y.size
    if n < 3:
        return y.copy()
    # Matriz de segundas diferencias D: (n-2) x n
    D = np.zeros((n - 2, n))
    for i in range(n - 2):
        D[i, i] = 1.0
        D[i, i + 1] = -2.0
        D[i, i + 2] = 1.0
    A = np.eye(n) + lam * (D.T @ D)
    return np.linalg.solve(A, y)


def output_gap_last(index_history: List[float], lam: float = HP_LAMBDA_MONTHLY) -> Optional[float]:
    """Brecha de producto (%) en el ÚLTIMO punto de la historia truncada del índice IMAE.

    Aplica el HP-filter sobre ``log(index)`` con SOLO los datos disponibles a la fecha
    (one-sided) y devuelve ``100 * (log(actual) − log(tendencia))`` en el último período.
    None si hay menos de 3 observaciones válidas.
    """
    vals = [v for v in index_history if v is not None and v > 0]
    if len(vals) < 3:
        return None
    log_idx = np.log(np.asarray(vals, dtype=float))
    trend = hp_filter(log_idx, lam)
    return float(100.0 * (log_idx[-1] - trend[-1]))


def inflation_gap(inflation: Optional[float], target: float = INFLATION_TARGET) -> Optional[float]:
    return None if inflation is None else float(inflation - target)


def real_rate(tpm: Optional[float], inflation: Optional[float]) -> Optional[float]:
    if tpm is None or inflation is None:
        return None
    return float(tpm - inflation)


def yoy(now: Optional[float], year_ago: Optional[float]) -> Optional[float]:
    """Variación interanual (%) entre el valor actual y el de ~12 meses atrás."""
    if now is None or year_ago is None or year_ago == 0:
        return None
    return float(100.0 * (now / year_ago - 1.0))
