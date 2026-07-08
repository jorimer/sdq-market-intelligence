"""Orquestación del modelo de TPM: entrena, persiste y sirve el forecast.

Persiste en ``AppSetting`` (shared) — modelo chico, sin migración ni importar de otro
módulo:
  • ``tpm_model``     → JSON con la regla de Taylor (coeficientes) + el clasificador
                        (pickle en base64) + resumen del panel + versión.
  • ``tpm_backtest``  → JSON del reporte de backtest (para un GET barato, patrón banca).

El entrenamiento (build panel → fit regla → fit XGBoost → backtest expanding-window) es
pesado (≈100 reentrenamientos en el backtest) → se dispara por la OPERACIÓN async
``tpm-model-train`` (hilo daemon), no por endpoint síncrono.
"""
from __future__ import annotations

import base64
import json
import logging
from collections import Counter
from datetime import datetime, timezone
from typing import Any, Dict, Optional, Tuple

from sqlalchemy.orm import Session

from modules.macro_monitor.tpm_modeling import backtest as bt
from modules.macro_monitor.tpm_modeling.classifier import TpmClassifier, build_xy
from modules.macro_monitor.tpm_modeling.dataset import build_panel, current_feature_row
from modules.macro_monitor.tpm_modeling.features import FEATURE_NAMES
from modules.macro_monitor.tpm_modeling.reaction_function import (
    ReactionFunction,
    fit_reaction_function,
)

logger = logging.getLogger("sdq.macro_monitor.tpm_modeling")

MODEL_KEY = "tpm_model"
BACKTEST_KEY = "tpm_backtest"

# Limitaciones estructurales, citadas en el forecast y el reporte (honestidad tipo Fitch).
CAVEATS = [
    "Análisis macro con incertidumbre; no constituye consejo de inversión.",
    "Features point-in-time con el rezago típico de publicación, pero sin vintages: se usa "
    "el valor final de cada serie (que pudo revisarse), no el disponible exacto ese día.",
    "No se incorporan la tasa de la Reserva Federal ni el riesgo país (EMBI): drivers "
    "externos relevantes ausentes del MVP.",
    "Panel corto y desbalanceado (145 de 190 decisiones son 'mantener'): las clases de "
    "corte y alza tienen pocos ejemplos.",
]


def _set_app_setting(db: Session, key: str, payload: Dict[str, Any]) -> None:
    from shared.settings.models import AppSetting

    row = db.query(AppSetting).filter(AppSetting.key == key).first()
    value = json.dumps(payload)
    if row is None:
        db.add(AppSetting(key=key, value=value, is_secret=False))
    else:
        row.value = value
    db.commit()


def _get_app_setting(db: Session, key: str) -> Optional[Dict[str, Any]]:
    from shared.settings.models import AppSetting

    row = db.query(AppSetting).filter(AppSetting.key == key).first()
    if row is None or not row.value:
        return None
    try:
        return json.loads(row.value)
    except (ValueError, TypeError):
        return None


def _panel_summary(rows) -> Dict[str, Any]:
    actions = Counter(r.action for r in rows)
    full = sum(1 for r in rows if all(r.features.get(n) is not None for n in FEATURE_NAMES))
    dates = [r.as_of for r in rows if r.as_of]
    return {
        "n_decisiones": len(rows),
        "acciones": dict(actions),
        "n_features_completas": full,
        "rango": [dates[0].isoformat(), dates[-1].isoformat()] if dates else None,
    }


def train_and_persist(db: Session, trained_by: Optional[str] = None,
                      set_phase=None) -> Dict[str, Any]:
    """Construye el panel, entrena regla + clasificador, corre el backtest y persiste todo."""
    set_phase = set_phase or (lambda _m: None)

    set_phase("construyendo panel point-in-time")
    rows = build_panel(db)
    if len(rows) < 30:
        raise ValueError(f"Panel insuficiente para entrenar ({len(rows)} decisiones).")
    summary = _panel_summary(rows)

    set_phase("estimando la regla de Taylor (OLS)")
    rf = fit_reaction_function(rows)

    set_phase("entrenando el clasificador XGBoost")
    X, y = build_xy(rows)
    clf = TpmClassifier().fit(X, y)

    set_phase("corriendo el backtest time-series (expanding window)")
    backtest = bt.run_backtest(rows)

    version = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    trained_at = datetime.now(timezone.utc).isoformat()
    _set_app_setting(db, MODEL_KEY, {
        "version": version,
        "trained_at": trained_at,
        "trained_by": trained_by,
        "feature_names": FEATURE_NAMES,
        "reaction_function": rf.to_dict(),
        "classifier_b64": base64.b64encode(clf.serialize()).decode("ascii"),
        "panel": summary,
    })
    _set_app_setting(db, BACKTEST_KEY, {
        "version": version, "generated_at": trained_at, **backtest,
    })
    logger.info("[tpm] modelo entrenado v=%s (%d decisiones); regla R2=%.3f",
                version, summary["n_decisiones"], rf.r2)
    return {
        "version": version,
        "panel": summary,
        "reaction_function_r2": rf.r2,
        "backtest": {
            "classifier": backtest.get("classifier", {}),
            "reaction_function": backtest.get("reaction_function", {}),
        },
    }


def load_model(db: Session) -> Optional[Tuple[ReactionFunction, TpmClassifier, Dict[str, Any]]]:
    """Carga (regla, clasificador, meta) desde AppSetting; None si no hay modelo entrenado."""
    payload = _get_app_setting(db, MODEL_KEY)
    if not payload:
        return None
    rf = ReactionFunction.from_dict(payload["reaction_function"])
    clf = TpmClassifier.deserialize(base64.b64decode(payload["classifier_b64"]))
    meta = {"version": payload.get("version"), "trained_at": payload.get("trained_at"),
            "panel": payload.get("panel")}
    return rf, clf, meta


def get_forecast(db: Session) -> Dict[str, Any]:
    """Pronóstico de la PRÓXIMA decisión de TPM: probabilidades + tasa implícita + sesgo."""
    loaded = load_model(db)
    if loaded is None:
        return {"has_model": False,
                "message": "El modelo de TPM no está entrenado. Corra la operación 'tpm-model-train'."}
    rf, clf, meta = loaded
    current = current_feature_row(db)
    feats = current["features"]
    tpm_vigente = current["tpm_vigente"]

    probs = clf.predict_proba(feats)
    implied = rf.predict(feats)
    bias = rf.bias(feats, tpm_vigente)
    _bias_label = ("restrictivo" if bias is not None and bias > 0.10 else
                   "expansivo" if bias is not None and bias < -0.10 else "neutral")
    top = max(probs, key=probs.get) if probs else None

    return {
        "has_model": True,
        "version": meta.get("version"),
        "trained_at": meta.get("trained_at"),
        "as_of": current["as_of"],
        "tpm_vigente": tpm_vigente,
        "clasificador": {
            "probabilidades": probs,   # {cut, hold, hike} o None si faltan features
            "decision_mas_probable": top,
        },
        "regla_taylor": {
            "tasa_implicita": implied,
            "sesgo_pp": bias,          # implícita − vigente
            "sesgo": _bias_label,      # restrictivo | expansivo | neutral
            "r2": rf.r2,
            "coeficientes": rf.coefficients,
        },
        "features_point_in_time": feats,
        "caveats": CAVEATS,
    }


def get_backtest(db: Session) -> Dict[str, Any]:
    """Reporte de backtest persistido; ``has_backtest`` False si no se ha corrido."""
    payload = _get_app_setting(db, BACKTEST_KEY)
    if not payload:
        return {"has_backtest": False,
                "message": "No hay backtest. Corra la operación 'tpm-model-train'."}
    return {"has_backtest": True, "caveats": CAVEATS, **payload}
