"""Clasificador XGBoost de la decisión de TPM (hold / cut / hike).

Sigue el patrón del modelo de rating de banca (:mod:`modules.banking_score.ml`) pero es
una clase liviana propia: el target es el SENTIDO de la decisión, no un tier. El dataset
está desbalanceado (145 holds de 190) → se entrena con *sample weights* balanceados y el
backtest reporta recall POR CLASE frente al baseline "siempre hold" (nunca solo accuracy).

Modelo chico (≈190 filas, 3 clases): árboles poco profundos para no sobreajustar.
"""
from __future__ import annotations

import pickle
from typing import Dict, List, Optional, Tuple

import numpy as np

from modules.macro_monitor.tpm_modeling.dataset import PanelRow
from modules.macro_monitor.tpm_modeling.features import FEATURE_NAMES

ACTIONS = ["cut", "hold", "hike"]

# Hiperparámetros conservadores para un panel pequeño y desbalanceado.
XGB_PARAMS = dict(
    n_estimators=200, max_depth=3, learning_rate=0.05,
    subsample=0.8, colsample_bytree=0.8, min_child_weight=2,
    objective="multi:softprob", eval_metric="mlogloss",
    random_state=42, n_jobs=1,
)


def build_xy(rows: List[PanelRow], feature_names: List[str] = FEATURE_NAMES,
             ) -> Tuple[np.ndarray, List[str]]:
    """(X, y) de las filas con TODAS las features presentes (target = action, siempre existe)."""
    X: List[List[float]] = []
    y: List[str] = []
    for r in rows:
        vec = [r.features.get(n) for n in feature_names]
        if any(v is None for v in vec):
            continue
        X.append([float(v) for v in vec])
        y.append(r.action)
    return np.asarray(X, dtype=float), y


def _sample_weights(y_idx: np.ndarray, n_classes: int) -> np.ndarray:
    """Pesos balanceados: inversamente proporcionales a la frecuencia de cada clase."""
    counts = np.bincount(y_idx, minlength=n_classes).astype(float)
    counts[counts == 0] = 1.0
    inv = len(y_idx) / (n_classes * counts)
    return inv[y_idx]


class TpmClassifier:
    """XGBoost multiclase para el sentido de la decisión de TPM."""

    def __init__(self, feature_names: List[str] = FEATURE_NAMES):
        self.feature_names = list(feature_names)
        self.model = None            # XGBClassifier
        self.classes_: List[str] = []  # índice del modelo → etiqueta de acción

    def fit(self, X: np.ndarray, y: List[str]) -> "TpmClassifier":
        from xgboost import XGBClassifier

        # Codifica las clases presentes en un orden estable (cut/hold/hike si están todas).
        present = [a for a in ACTIONS if a in set(y)]
        self.classes_ = present
        idx = {a: i for i, a in enumerate(present)}
        y_idx = np.asarray([idx[a] for a in y], dtype=int)

        params = dict(XGB_PARAMS, num_class=len(present))
        self.model = XGBClassifier(**params)
        self.model.fit(X, y_idx, sample_weight=_sample_weights(y_idx, len(present)))
        return self

    def predict_proba(self, feats: Dict[str, Optional[float]]) -> Optional[Dict[str, float]]:
        """Distribución de probabilidad sobre {cut, hold, hike}; None si falta un feature."""
        if self.model is None:
            raise RuntimeError("Clasificador no entrenado.")
        vec = [feats.get(n) for n in self.feature_names]
        if any(v is None for v in vec):
            return None
        X = np.asarray([[float(v) for v in vec]], dtype=float)
        probs = self.model.predict_proba(X)[0]
        return {a: float(p) for a, p in zip(self.classes_, probs)}

    # ── Serialización (pickle → bytes, persistido en base64 por el service) ──
    def serialize(self) -> bytes:
        return pickle.dumps({
            "feature_names": self.feature_names,
            "classes_": self.classes_,
            "model": self.model,
        })

    @classmethod
    def deserialize(cls, blob: bytes) -> "TpmClassifier":
        payload = pickle.loads(blob)
        obj = cls(payload["feature_names"])
        obj.classes_ = payload["classes_"]
        obj.model = payload["model"]
        return obj
