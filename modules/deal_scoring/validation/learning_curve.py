"""Curva de aprendizaje del Deal Scoring — ¿ya vale la pena el modelo entrenado?

Responde, con datos, la pregunta de graduación rúbrica→XGBoost: a medida que el
registro `HistoricalDeal` cosecha labels, entrena+**cross-valida** y reporta el AUC
con su intervalo de confianza (bootstrap). El criterio de graduación NO es un "N=200"
arbitrario, sino que el **IC inferior del AUC cruce un umbral útil** (anti-fabricación:
un modelo no se comunica como predictivo hasta que su validación lo gane — mismo
estándar que los Gate E de los ejes).

**Fuga de información (leakage):** la graduación corre SOLO sobre labels *ex-ante*
(`retrospective=False`) — scoreados antes de conocer el outcome. Los labels
*retrospectivos* (backfill histórico, etiquetados con el resultado ya conocido)
inflan el AUC artificialmente y NO gradúan el modelo; se reportan aparte como un
diagnóstico in-sample explícitamente marcado como sujeto a fuga.

Lee SOLO la tabla del propio módulo (`HistoricalDeal`) — sin acople cross-módulo.
"""
from typing import Any, Dict, List, Optional

from sqlalchemy.orm import Session

# Umbral de graduación: el IC-inferior del AUC en CV debe superarlo.
GRADUATION_AUC_FLOOR = 0.65
# Mínimos para una CV honesta (debajo de esto no se reporta AUC — sería ruido).
MIN_LABELED = 20
MIN_PER_CLASS = 5

_STAGE_ORD = {"initial": 1, "due_diligence": 2, "term_sheet": 3, "legal": 4}


def _features(d) -> List[float]:
    import math
    size = float(d.deal_size_usd) if d.deal_size_usd is not None else 0.0
    return [
        _STAGE_ORD.get((d.deal_stage.value if d.deal_stage else None), 0),
        math.log1p(max(0.0, size)),
        float(d.equity_required_pct) if d.equity_required_pct is not None else 0.0,
        float(d.days_since_first_contact) if d.days_since_first_contact is not None else 0.0,
        # señales de analista (hoy casi todas None → 0; entran cuando se backfilleen)
        float(d.promoter_track_record or 0),
        float(d.financial_quality or 0),
        float(d.market_validation or 0),
        float(d.regulatory_readiness or 0),
    ]


def _cv_auc(deals: List[Any], n_boot: int) -> Optional[Dict[str, Any]]:
    """CV-AUC + IC bootstrap sobre un set de deals etiquetados, o None si es
    insuficiente para una validación honesta (N o balance por clase)."""
    n = len(deals)
    n_pos = sum(1 for d in deals if d.closed_successfully)
    n_neg = n - n_pos
    if n < MIN_LABELED or n_pos < MIN_PER_CLASS or n_neg < MIN_PER_CLASS:
        return None

    import numpy as np
    from sklearn.linear_model import LogisticRegression
    from sklearn.metrics import roc_auc_score
    from sklearn.model_selection import StratifiedKFold, cross_val_predict
    from sklearn.preprocessing import StandardScaler
    from sklearn.pipeline import make_pipeline

    X = np.array([_features(d) for d in deals], dtype=float)
    y = np.array([1 if d.closed_successfully else 0 for d in deals], dtype=int)

    k = int(min(5, n_neg, n_pos))
    pipe = make_pipeline(StandardScaler(), LogisticRegression(max_iter=1000, C=1.0))
    cv = StratifiedKFold(n_splits=k, shuffle=True, random_state=42)
    # Predicciones out-of-fold (cada obs predicha por un modelo que NO la vio).
    proba = cross_val_predict(pipe, X, y, cv=cv, method="predict_proba")[:, 1]
    auc = float(roc_auc_score(y, proba))

    # IC bootstrap del AUC sobre las predicciones OOF.
    rng = np.random.default_rng(42)
    boots = []
    idx = np.arange(n)
    for _ in range(n_boot):
        s = rng.choice(idx, size=n, replace=True)
        if len(np.unique(y[s])) < 2:
            continue
        boots.append(roc_auc_score(y[s], proba[s]))
    lo, hi = ((float(np.percentile(boots, 2.5)), float(np.percentile(boots, 97.5)))
              if boots else (None, None))
    return {
        "n_folds": k,
        "cv_auc": round(auc, 3),
        "auc_ci": [round(lo, 3) if lo is not None else None,
                   round(hi, 3) if hi is not None else None],
        "_lo": lo,
    }


def build_report(db: Session, n_boot: int = 1000) -> Dict[str, Any]:
    from modules.deal_scoring.models.models import HistoricalDeal

    labeled = db.query(HistoricalDeal).filter(
        HistoricalDeal.closed_successfully.isnot(None)
    ).all()
    n = len(labeled)
    n_pos = sum(1 for d in labeled if d.closed_successfully)
    n_neg = n - n_pos

    # Solo los labels ex-ante (scoreados antes de conocer el outcome) gradúan: los
    # retrospectivos (backfill) tienen fuga y se reportan aparte como diagnóstico.
    ex_ante = [d for d in labeled if not d.retrospective]
    retro = [d for d in labeled if d.retrospective]
    n_ex_ante = len(ex_ante)

    base = {
        "n_labeled": n, "n_closed": n_pos, "n_lost": n_neg,
        "n_ex_ante": n_ex_ante, "n_retrospective": len(retro),
        "graduation_floor": GRADUATION_AUC_FLOOR,
        "method": "logistic regression + StratifiedKFold CV, IC bootstrap del AUC; "
                  "graduación SOLO sobre labels ex-ante (libres de fuga)",
    }

    # Diagnóstico in-sample sobre los retrospectivos — NUNCA gradúa (puede tener fuga).
    diag = _cv_auc(retro, n_boot)
    retrospective_diagnostic = None
    if diag is not None:
        retrospective_diagnostic = {
            "n": len(retro), "cv_auc": diag["cv_auc"], "auc_ci": diag["auc_ci"],
            "note": "Diagnóstico in-sample sobre labels retrospectivos (backfill). NO "
                    "se usa para graduar: al etiquetarse con el outcome ya conocido, el "
                    "AUC puede estar inflado por fuga de información. La señal de "
                    "graduación honesta solo viene de la cosecha going-forward.",
        }

    fit = _cv_auc(ex_ante, n_boot) if n_ex_ante else None
    caveats = [
        "Graduación libre de fuga: solo cuentan labels ex-ante (scoreados antes de "
        "conocer el outcome). Los retrospectivos enriquecen la rúbrica, no la validación.",
        "Modelo reducido: cuando faltan las 4 señales de analista entran como 0; el "
        "modelo se apoya en los features estructurales (etapa, tamaño, equity, días).",
        "Con N pequeño el AUC es de alta varianza: el IC ancho es esperado y honesto.",
    ]

    if fit is None:
        n_ex_pos = sum(1 for d in ex_ante if d.closed_successfully)
        msg = (
            f"{n} labels en el registro, de los cuales {n_ex_ante} son cosecha ex-ante "
            f"(libre de fuga). Insuficiente para graduar (se requieren ≥{MIN_LABELED} "
            f"ex-ante y ≥{MIN_PER_CLASS} por clase; hoy +{n_ex_pos}/-{n_ex_ante - n_ex_pos}). "
            "El Deal Scoring sigue en RÚBRICA declarada hasta cosechar suficientes "
            "outcomes going-forward."
        )
        return {**base, "computed": False, "status": "rubrica", "ready_for_model": False,
                "message": msg, "retrospective_diagnostic": retrospective_diagnostic,
                "caveats": caveats}

    lo = fit["_lo"]
    ready = lo is not None and lo > GRADUATION_AUC_FLOOR
    return {
        **base, "computed": True,
        "n_folds": fit["n_folds"], "cv_auc": fit["cv_auc"], "auc_ci": fit["auc_ci"],
        "ready_for_model": ready,
        "status": "modelo" if ready else "rubrica",
        "message": (
            f"AUC en CV = {fit['cv_auc']:.3f} (IC95% {fit['auc_ci'][0]:.3f}–{fit['auc_ci'][1]:.3f}) "
            f"sobre {n_ex_ante} labels ex-ante. "
            + ("El IC inferior supera el umbral: un modelo entrenado ya es viable; "
               "puede graduarse de rúbrica."
               if ready else
               f"El IC inferior ({lo:.3f}) no supera {GRADUATION_AUC_FLOOR}: la señal "
               "aún es inestable (N pequeño). Sigue en RÚBRICA — honestidad sobre la "
               "fuerza de la señal, no sobre-promesa.")
        ),
        "retrospective_diagnostic": retrospective_diagnostic,
        "caveats": caveats,
    }
