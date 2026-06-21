"""Curva de aprendizaje del Deal Scoring — ¿ya vale la pena el modelo entrenado?

Responde, con datos, la pregunta de graduación rúbrica→XGBoost: a medida que el
registro `HistoricalDeal` cosecha labels, entrena+**cross-valida** y reporta el AUC
con su intervalo de confianza (bootstrap). El criterio de graduación NO es un "N=200"
arbitrario, sino que el **IC inferior del AUC cruce un umbral útil** (anti-fabricación:
un modelo no se comunica como predictivo hasta que su validación lo gane — mismo
estándar que los Gate E de los ejes).

Lee SOLO la tabla del propio módulo (`HistoricalDeal`) — sin acople cross-módulo.
"""
from typing import Any, Dict, List

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


def build_report(db: Session, n_boot: int = 1000) -> Dict[str, Any]:
    from modules.deal_scoring.models.models import HistoricalDeal

    labeled = db.query(HistoricalDeal).filter(
        HistoricalDeal.closed_successfully.isnot(None)
    ).all()
    n = len(labeled)
    n_pos = sum(1 for d in labeled if d.closed_successfully)
    n_neg = n - n_pos

    base = {
        "n_labeled": n, "n_closed": n_pos, "n_lost": n_neg,
        "graduation_floor": GRADUATION_AUC_FLOOR,
        "method": "logistic regression + StratifiedKFold CV, IC bootstrap del AUC",
    }

    if n < MIN_LABELED or n_pos < MIN_PER_CLASS or n_neg < MIN_PER_CLASS:
        return {**base, "computed": False, "status": "rubrica",
                "message": f"Insuficiente para una validación honesta (N={n}, +{n_pos}/-{n_neg}; "
                           f"se requieren ≥{MIN_LABELED} y ≥{MIN_PER_CLASS} por clase). El "
                           "Deal Scoring sigue en RÚBRICA declarada hasta cosechar más labels.",
                "ready_for_model": False}

    import numpy as np
    from sklearn.linear_model import LogisticRegression
    from sklearn.metrics import roc_auc_score
    from sklearn.model_selection import StratifiedKFold, cross_val_predict
    from sklearn.preprocessing import StandardScaler
    from sklearn.pipeline import make_pipeline

    X = np.array([_features(d) for d in labeled], dtype=float)
    y = np.array([1 if d.closed_successfully else 0 for d in labeled], dtype=int)

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
    lo, hi = (float(np.percentile(boots, 2.5)), float(np.percentile(boots, 97.5))) if boots else (None, None)

    ready = lo is not None and lo > GRADUATION_AUC_FLOOR
    return {
        **base, "computed": True,
        "n_folds": k,
        "cv_auc": round(auc, 3),
        "auc_ci": [round(lo, 3) if lo is not None else None,
                   round(hi, 3) if hi is not None else None],
        "ready_for_model": ready,
        "status": "modelo" if ready else "rubrica",
        "message": (
            f"AUC en CV = {auc:.3f} (IC95% {lo:.3f}–{hi:.3f}). "
            + ("El IC inferior supera el umbral: un modelo entrenado ya es viable; "
               "puede graduarse de rúbrica."
               if ready else
               f"El IC inferior ({lo:.3f}) no supera {GRADUATION_AUC_FLOOR}: la señal "
               "aún es inestable (N pequeño). Sigue en RÚBRICA — honestidad sobre la "
               "fuerza de la señal, no sobre-promesa.")
        ),
        "caveats": [
            "Modelo reducido: las 4 señales de analista están casi todas vacías (backfill "
            "pendiente); hoy entrena sobre features estructurales (etapa, tamaño, equity, días).",
            "Con N pequeño el AUC es de alta varianza: el IC ancho es esperado y honesto.",
        ],
    }
