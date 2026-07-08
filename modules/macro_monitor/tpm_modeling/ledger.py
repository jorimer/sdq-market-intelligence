"""Track record EN VIVO del modelo de TPM: congela pronósticos y los puntúa contra la
decisión real cuando el BCRD la publica.

Flujo (lo orquesta la operación ``tpm-model-train``, disparada tras ``bcrd-comunicados-sync``):
  1. ``score_pending``  — puntúa el pronóstico pendiente contra las decisiones ya conocidas.
  2. (re-entrenamiento del modelo, en :mod:`service`)
  3. ``snapshot_forecast`` — congela un pronóstico nuevo para la PRÓXIMA decisión.

Regla de casamiento: hay a lo sumo UN pronóstico ``pending`` (el vigente). Cuando llega la
primera decisión posterior a su fecha, ese pronóstico se puntúa y pasa a ``scored``; el
siguiente snapshot abre uno nuevo. Cada decisión se puntúa una sola vez. Solo se puntúan
pronósticos GENUINAMENTE en vivo (nunca se siembra el pasado — eso es el backtest).
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from sqlalchemy.orm import Session

from modules.macro_monitor.tpm_modeling import service as tpm_service
from modules.macro_monitor.tpm_modeling.dataset import _parse_date
from modules.macro_monitor.tpm_modeling.models import TpmForecastLog

logger = logging.getLogger("sdq.macro_monitor.tpm_modeling.ledger")

ACTIONS = ["cut", "hold", "hike"]


def _probs(row: TpmForecastLog) -> Optional[Dict[str, float]]:
    if row.prob_hold is None:
        return None
    return {"cut": row.prob_cut or 0.0, "hold": row.prob_hold or 0.0, "hike": row.prob_hike or 0.0}


def _brier(probs: Optional[Dict[str, float]], realized: str) -> Optional[float]:
    """Brier multiclase: Σ_k (p_k − 1[k==realizado])². Menor es mejor (0 = perfecto)."""
    if not probs:
        return None
    return float(sum((probs.get(k, 0.0) - (1.0 if k == realized else 0.0)) ** 2 for k in ACTIONS))


def snapshot_forecast(db: Session) -> Dict[str, Any]:
    """Congela el pronóstico vigente como fila ``pending`` (a lo sumo una).

    Si ya hay un pendiente sin puntuar, lo REFRESCA con el dato más reciente (sigue siendo
    el pronóstico de la próxima decisión). No hace nada si el modelo no está entrenado o si
    faltan probabilidades (features incompletas)."""
    fc = tpm_service.get_forecast(db)
    if not fc.get("has_model"):
        return {"snapshotted": False, "reason": "modelo no entrenado"}
    probs = (fc.get("clasificador") or {}).get("probabilidades")
    rt = fc.get("regla_taylor") or {}

    pending = (db.query(TpmForecastLog)
               .filter(TpmForecastLog.status == "pending")
               .order_by(TpmForecastLog.as_of.desc()).first())
    row = pending or TpmForecastLog(status="pending")
    row.as_of = fc.get("as_of")
    row.model_version = fc.get("version")
    row.prob_cut = (probs or {}).get("cut")
    row.prob_hold = (probs or {}).get("hold")
    row.prob_hike = (probs or {}).get("hike")
    row.predicted_action = (fc.get("clasificador") or {}).get("decision_mas_probable")
    row.implied_rate = rt.get("tasa_implicita")
    row.bias_pp = rt.get("sesgo_pp")
    row.tpm_vigente = fc.get("tpm_vigente")
    row.features = fc.get("features_point_in_time")
    if pending is None:
        db.add(row)
    db.commit()
    return {"snapshotted": True, "as_of": row.as_of, "predicted_action": row.predicted_action,
            "refreshed": pending is not None}


def _decisions(db: Session) -> List[Dict[str, Any]]:
    """Decisiones reales de TPM (con sentido), ascendentes por fecha."""
    from modules.macro_monitor.comunicados.service import _decisions_desc

    out = []
    for r in _decisions_desc(db):
        d = _parse_date(r.decision_date)
        if d is not None and r.action:
            out.append({"date": d, "action": r.action, "tpm_level": r.tpm_level,
                        "article_id": r.article_id, "date_iso": r.decision_date})
    out.sort(key=lambda x: x["date"])
    return out


def score_pending(db: Session) -> Dict[str, Any]:
    """Puntúa los pronósticos ``pending`` contra la primera decisión real posterior.

    Cada decisión se casa con a lo sumo un pronóstico (no doble conteo). Devuelve cuántos
    se puntuaron."""
    pendings = (db.query(TpmForecastLog)
                .filter(TpmForecastLog.status == "pending")
                .order_by(TpmForecastLog.as_of.asc()).all())
    if not pendings:
        return {"scored": 0}

    decisions = _decisions(db)
    already = {r.matched_article_id for r in
               db.query(TpmForecastLog).filter(TpmForecastLog.status == "scored").all()
               if r.matched_article_id is not None}

    scored = 0
    for p in pendings:
        pa = _parse_date(p.as_of)
        if pa is None:
            continue
        match = next((d for d in decisions
                      if d["date"] > pa and d["article_id"] not in already), None)
        if match is None:
            continue  # aún no hay decisión posterior → sigue pendiente
        probs = _probs(p)
        p.matched_article_id = match["article_id"]
        p.realized_action = match["action"]
        p.realized_tpm_level = match["tpm_level"]
        p.realized_date = match["date_iso"]
        p.correct = (p.predicted_action == match["action"]) if p.predicted_action else None
        p.brier = _brier(probs, match["action"])
        p.level_abs_error = (abs(p.implied_rate - match["tpm_level"])
                             if p.implied_rate is not None and match["tpm_level"] is not None else None)
        p.scored_at = datetime.now(timezone.utc)
        p.status = "scored"
        already.add(match["article_id"])
        scored += 1
    db.commit()
    if scored:
        logger.info("[tpm] track record: %d pronóstico(s) puntuado(s)", scored)
    return {"scored": scored}


def _row_dict(r: TpmForecastLog) -> Dict[str, Any]:
    return {
        "as_of": r.as_of, "model_version": r.model_version,
        "probabilidades": _probs(r), "decision_pronosticada": r.predicted_action,
        "tasa_implicita": r.implied_rate, "sesgo_pp": r.bias_pp,
        "realized_action": r.realized_action, "realized_tpm_level": r.realized_tpm_level,
        "realized_date": r.realized_date, "correct": r.correct,
        "brier": r.brier, "level_abs_error": r.level_abs_error,
    }


def track_record(db: Session) -> Dict[str, Any]:
    """Métricas EN VIVO acumuladas + el pronóstico vigente. La muestra crece ~1/reunión."""
    scored = (db.query(TpmForecastLog)
              .filter(TpmForecastLog.status == "scored")
              .order_by(TpmForecastLog.realized_date.asc()).all())
    pending = (db.query(TpmForecastLog)
               .filter(TpmForecastLog.status == "pending")
               .order_by(TpmForecastLog.as_of.desc()).first())

    n = len(scored)
    correct_vals = [r.correct for r in scored if r.correct is not None]
    brier_vals = [r.brier for r in scored if r.brier is not None]
    level_errs = [r.level_abs_error for r in scored if r.level_abs_error is not None]

    # Recall por clase + matriz de confusión (la señal honesta con tanto 'hold').
    per_class: Dict[str, Dict[str, Any]] = {}
    confusion = {a: {b: 0 for b in ACTIONS} for a in ACTIONS}
    for a in ACTIONS:
        real_a = [r for r in scored if r.realized_action == a]
        hits = sum(1 for r in real_a if r.predicted_action == a)
        per_class[a] = {"support": len(real_a),
                        "recall": (hits / len(real_a)) if real_a else None}
    for r in scored:
        if r.realized_action in confusion and r.predicted_action in confusion[r.realized_action]:
            confusion[r.realized_action][r.predicted_action] += 1

    # Referencia del backtest (para contrastar en vivo vs histórico).
    bt = tpm_service.get_backtest(db)
    bt_ref = None
    if bt.get("has_backtest") and bt.get("classifier", {}).get("ok"):
        c = bt["classifier"]
        bt_ref = {"macro_f1": c.get("macro_f1"), "accuracy": c.get("accuracy"),
                  "baseline_always_hold_accuracy": c.get("baseline_always_hold_accuracy")}

    return {
        "has_data": n > 0 or pending is not None,
        "n_scored": n,
        "hit_rate": (sum(correct_vals) / len(correct_vals)) if correct_vals else None,
        "brier_medio": (sum(brier_vals) / len(brier_vals)) if brier_vals else None,
        "mae_nivel": (sum(level_errs) / len(level_errs)) if level_errs else None,
        "per_class": per_class,
        "confusion_matrix": {"labels": ACTIONS, "matrix": [[confusion[a][b] for b in ACTIONS] for a in ACTIONS]},
        "backtest_referencia": bt_ref,
        "historial": [_row_dict(r) for r in scored[-24:]],
        "pronostico_vigente": _row_dict(pending) if pending else None,
        "nota": (
            "Track record PROSPECTIVO: cada fila es un pronóstico congelado ANTES de la "
            "decisión y puntuado con la decisión real. Crece ~1 por reunión de la Junta "
            "Monetaria; con muestra chica, léase junto al backtest histórico. La métrica "
            "central es el Brier (calibración) y el recall por clase, no el % de aciertos "
            "(inflado por el predominio de 'mantener')."
        ),
        "caveats": tpm_service.CAVEATS,
    }
