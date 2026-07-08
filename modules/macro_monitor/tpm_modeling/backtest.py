"""Backtest TIME-SERIES (expanding window, out-of-sample) del modelo de TPM.

Regla de oro: NUNCA un split aleatorio. Se ordena el panel cronológicamente y, en cada
paso, se entrena con TODO lo anterior y se predice la decisión siguiente (one-step-ahead).
Así el backtest respeta la flecha del tiempo igual que el panel point-in-time.

Se reporta:
  • Clasificador: recall/precisión/F1 POR CLASE + macro-F1 + accuracy, SIEMPRE contra el
    baseline ingenuo "siempre hold" (que ya acierta ~76% por el desbalance — accuracy sola
    engaña). Más la matriz de confusión.
  • Regla de Taylor: acierto DIRECCIONAL (¿el sesgo implícito anticipa el sentido real?) y
    error absoluto medio del nivel implícito.

Si los números salen pobres, se reportan tal cual: es análisis macro con incertidumbre,
no un oráculo.
"""
from __future__ import annotations

from datetime import timedelta
from typing import Dict, List

import numpy as np

from modules.macro_monitor.tpm_modeling.classifier import (
    TpmClassifier,
    build_xy,
)
from modules.macro_monitor.tpm_modeling.dataset import PanelRow
from modules.macro_monitor.tpm_modeling.features import FEATURE_NAMES, TAYLOR_FEATURES
from modules.macro_monitor.tpm_modeling.reaction_function import fit_reaction_function

# Mínimo de decisiones de entrenamiento antes de empezar a predecir (cubre los ciclos de
# corte/alza tempranos para que las clases minoritarias estén representadas al entrenar).
MIN_TRAIN = 90


def _classifier_backtest(rows: List[PanelRow], min_train: int) -> Dict:
    """Expanding-window one-step-ahead del clasificador."""
    from sklearn.metrics import (
        confusion_matrix,
        precision_recall_fscore_support,
    )

    # Solo filas con features completas; ordenadas por fecha (build_panel ya viene asc).
    full = [r for r in rows if all(r.features.get(n) is not None for n in FEATURE_NAMES)]
    if len(full) <= min_train + 5:
        return {"ok": False, "reason": f"Panel insuficiente para backtest ({len(full)} filas completas)."}

    y_true: List[str] = []
    y_pred: List[str] = []
    for i in range(min_train, len(full)):
        train = full[:i]
        X_tr, y_tr = build_xy(train)
        if len(set(y_tr)) < 2:
            continue  # sin variación de clase no hay nada que aprender
        clf = TpmClassifier().fit(X_tr, y_tr)
        probs = clf.predict_proba(full[i].features)
        if probs is None:
            continue
        y_pred.append(max(probs, key=probs.get))
        y_true.append(full[i].action)

    if not y_true:
        return {"ok": False, "reason": "No se generó ninguna predicción out-of-sample."}

    labels = ["cut", "hold", "hike"]
    prec, rec, f1, support = precision_recall_fscore_support(
        y_true, y_pred, labels=labels, zero_division=0)
    per_class = {
        lab: {"precision": float(prec[j]), "recall": float(rec[j]),
              "f1": float(f1[j]), "support": int(support[j])}
        for j, lab in enumerate(labels)
    }
    n = len(y_true)
    accuracy = float(np.mean([t == p for t, p in zip(y_true, y_pred)]))
    # Baseline "siempre hold".
    base_acc = float(np.mean([t == "hold" for t in y_true]))
    macro_f1 = float(np.mean(f1))
    cm = confusion_matrix(y_true, y_pred, labels=labels).tolist()
    return {
        "ok": True,
        "n_test": n,
        "accuracy": accuracy,
        "baseline_always_hold_accuracy": base_acc,
        "beats_baseline": accuracy > base_acc,
        "macro_f1": macro_f1,
        "per_class": per_class,
        "confusion_matrix": {"labels": labels, "matrix": cm},
        "min_train": min_train,
    }


# Horizontes (meses) para evaluar el poder DIRECCIONAL del sesgo de la regla. Una regla de
# Taylor describe la trayectoria de mediano plazo de la tasa, no la decisión de la próxima
# reunión (que dominan los "hold" y que predice el clasificador). Por eso el sesgo se juzga
# contra el CAMBIO de la TPM a 6-12 meses, no contra la acción de esa misma reunión.
BIAS_HORIZONS_M = (6, 12)
_BIAS_DEADBAND = 0.05  # ignora sesgos/cambios ~nulos al medir coincidencia de signo


def _directional_signal(pairs: List[tuple]) -> Dict:
    """Coincidencia de signo y correlación entre el sesgo y el cambio futuro de la TPM."""
    if len(pairs) < 6:
        return {"n": len(pairs), "sign_match": None, "correlacion": None}
    xs = np.asarray([p[0] for p in pairs], dtype=float)
    ys = np.asarray([p[1] for p in pairs], dtype=float)
    matches = [(x > 0) == (y > 0) for x, y in pairs
               if abs(x) > _BIAS_DEADBAND and abs(y) > 1e-6]
    corr = float(np.corrcoef(xs, ys)[0, 1]) if xs.std() > 0 and ys.std() > 0 else None
    return {
        "n": len(pairs),
        "n_con_senal": len(matches),
        "sign_match": float(np.mean(matches)) if matches else None,
        "correlacion": corr,
    }


def _reaction_backtest(rows: List[PanelRow], min_train: int) -> Dict:
    """Expanding-window de la regla de Taylor: MAE del NIVEL + poder direccional a 6-12m."""
    usable = [r for r in rows
              if r.tpm_level is not None and all(r.features.get(n) is not None for n in TAYLOR_FEATURES)]
    if len(usable) <= min_train + 5:
        return {"ok": False, "reason": f"Panel insuficiente ({len(usable)} filas con nivel)."}

    abs_err: List[float] = []
    # sesgo vs cambio futuro de la TPM, por horizonte.
    bias_change: Dict[int, List[tuple]] = {h: [] for h in BIAS_HORIZONS_M}
    for i in range(min_train, len(usable)):
        try:
            rf = fit_reaction_function(usable[:i])
        except ValueError:
            continue
        row = usable[i]
        implied = rf.predict(row.features)
        if implied is None:
            continue
        abs_err.append(abs(implied - row.tpm_level))
        bias = rf.bias(row.features, row.tpm_prev)
        if bias is None:
            continue
        for h in BIAS_HORIZONS_M:
            cutoff = row.as_of + timedelta(days=30 * h)
            future = [u for u in usable[i + 1:] if u.as_of <= cutoff]
            if future:
                bias_change[h].append((bias, future[-1].tpm_level - row.tpm_level))

    if not abs_err:
        return {"ok": False, "reason": "No se generó ninguna tasa implícita out-of-sample."}
    return {
        "ok": True,
        "n_test": len(abs_err),
        "mae_nivel": float(np.mean(abs_err)),
        "direccional": {
            f"horizonte_{h}m": _directional_signal(bias_change[h]) for h in BIAS_HORIZONS_M
        },
        "nota_direccional": (
            "El sesgo (tasa implícita − vigente) anticipa la DIRECCIÓN de la TPM a 6-12 meses, "
            "no la decisión de la próxima reunión; esa la predice el clasificador."
        ),
        "min_train": min_train,
    }


def run_backtest(rows: List[PanelRow], min_train: int = MIN_TRAIN) -> Dict:
    """Backtest completo (clasificador + regla) sobre el panel."""
    return {
        "n_panel": len(rows),
        "classifier": _classifier_backtest(rows, min_train),
        "reaction_function": _reaction_backtest(rows, min_train),
    }
