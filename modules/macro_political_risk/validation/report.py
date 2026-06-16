"""IRMP backtest report — discrimination + convergent validity, with honesty.

Assembles: the historical panel, distress labels, Gini/AR with a bootstrap CI,
the realized-distress rate per IRMP band, and a convergent-validity check
(current IRMP rank vs S&P sovereign-rating rank). With N=5 countries this is
PRELIMINARY/DIRECTIONAL, not Basel-grade — the report says so (plan §6.5).
"""
from typing import Dict, List, Optional, Tuple

from modules.macro_political_risk.validation.historical import build_panel
from modules.macro_political_risk.validation.outcomes import (
    label_panel,
    label_panel_governance,
)
from shared.doctrine import load_doctrine_raw
from shared.validation.metrics import (
    deterioration_rate_by_tier,
    gini_bootstrap_ci,
)

BAND_ORDER = ["Bajo", "Moderado", "Elevado", "Alto"]  # best → worst (risk)


def _rank(xs: List[float]) -> List[float]:
    """Average ranks (ties shared), ascending."""
    order = sorted(range(len(xs)), key=lambda i: xs[i])
    ranks = [0.0] * len(xs)
    i = 0
    while i < len(order):
        j = i
        while j + 1 < len(order) and xs[order[j + 1]] == xs[order[i]]:
            j += 1
        avg = (i + j) / 2.0 + 1.0
        for k in range(i, j + 1):
            ranks[order[k]] = avg
        i = j + 1
    return ranks


def _spearman(xs: List[float], ys: List[float]) -> Optional[float]:
    n = len(xs)
    if n < 3:
        return None
    rx, ry = _rank(xs), _rank(ys)
    mx, my = sum(rx) / n, sum(ry) / n
    cov = sum((a - mx) * (b - my) for a, b in zip(rx, ry))
    vx = sum((a - mx) ** 2 for a in rx)
    vy = sum((b - my) ** 2 for b in ry)
    if vx <= 0 or vy <= 0:
        return None
    return round(cov / (vx * vy) ** 0.5, 3)


def _convergent_validity(series, panel: List[Dict]) -> Tuple[Optional[float], List[Dict]]:
    """Spearman of the latest-year IRMP vs the declared S&P rating score per country."""
    doc = load_doctrine_raw("regulatory")
    ratings = doc.get("sovereign_ratings", {})
    scale = doc.get("rating_scale", {})
    latest_year = max((r["year"] for r in panel), default=None)
    pairs: List[Dict] = []
    for r in panel:
        if r["year"] != latest_year:
            continue
        info = ratings.get(r["iso"])
        score = scale.get(info.get("rating")) if isinstance(info, dict) else None
        if score is not None:
            pairs.append({"iso": r["iso"], "irmp": r["irmp_score"],
                          "rating": info.get("rating"), "rating_score": float(score)})
    if len(pairs) < 3:
        return None, pairs
    rho = _spearman([p["irmp"] for p in pairs], [p["rating_score"] for p in pairs])
    return rho, pairs


def _metrics_for(labeled: List[Dict]) -> Dict:
    """Gini (+ bootstrap CI), distress-by-band and counts for a labeled panel."""
    scores = [r["irmp_score"] for r in labeled]
    labels = [r["label"] for r in labeled]
    bands = [r["risk_band"] for r in labeled]
    gini, lo, hi = gini_bootstrap_ci(scores, labels)
    rows, monotonic = deterioration_rate_by_tier(bands, labels, BAND_ORDER)
    n_events = sum(labels)
    years = sorted({r["year"] for r in labeled})
    return {
        "n_observations": len(labeled),
        "n_events": n_events,
        "event_rate": round(n_events / len(labeled), 3) if labeled else None,
        "years": [years[0], years[-1]] if years else None,
        "gini": None if gini is None else round(gini, 3),
        "gini_ci": [None if lo is None else round(lo, 3),
                    None if hi is None else round(hi, 3)],
        "distress_by_band": rows,
        "monotonic": monotonic,
    }


def build_backtest_report(series: Optional[Dict] = None,
                          events: Optional[Dict] = None) -> Dict:  # pragma: no cover - network in build_panel/BQ
    """Run the IRMP backtest. PRIMARY outcome = political-instability spikes (GDELT
    events, the construct the IRMP targets, independent of the historical core);
    SECONDARY = macro-fiscal distress (shown for contrast, overlaps with inputs).
    """
    from modules.macro_political_risk.validation.historical import fetch_series
    from shared.data.gdelt_bq_client import fetch_instability_events
    if series is None:
        series = fetch_series()
    if events is None:
        events = fetch_instability_events(start_year=2012)
    panel = build_panel(series)

    governance = _metrics_for(label_panel_governance(panel, events))
    credit = _metrics_for(label_panel(series, panel))
    rho, pairs = _convergent_validity(series, panel)

    return {
        "primary_outcome": "instability_spike",
        "n_countries": len({r["iso"] for r in panel}),
        "governance": governance,     # IRMP vs realized political instability (fair)
        "credit": credit,             # IRMP vs macro-fiscal distress (contrast)
        "convergent_validity": {"spearman_irmp_vs_rating": rho, "pairs": pairs},
        "disclaimer": (
            "Validación PRELIMINAR y DIRECCIONAL, no grado-Basilea: 5 países "
            "(N pequeño). El outcome PRIMARIO es inestabilidad política realizada "
            "(spikes de eventos GDELT) — el constructo que el IRMP sí mide. Es "
            "independiente del IRMP histórico, cuya dimensión de eventos queda en "
            "valores declarados estáticos (no de GDELT), así el label no puede "
            "filtrarse del score. El outcome de crédito se muestra como contraste "
            "(solapa con inputs y mide otro riesgo)."
        ),
    }
