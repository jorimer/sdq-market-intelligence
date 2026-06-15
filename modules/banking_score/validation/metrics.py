"""Discrimination metrics for the rating backtest (deterministic, OOS-free).

The score is "lower = riskier". We measure whether it ranks future deterioration
correctly via the Accuracy Ratio (Gini = 2·AUC − 1), and we report the realized
deterioration rate per SDQ tier (which should rise as the tier worsens).

Pure functions — no DB, no I/O — so they're unit-testable against known Gini.
"""
import bisect
import random
from typing import Dict, List, Optional, Tuple


def auc_low_score_risk(scores: List[float], labels: List[int]) -> Optional[float]:
    """AUC for predicting ``label==1`` (deterioration) from a LOW score.

    Equals P(score(event) < score(non-event)) + ½·P(tie), the Mann-Whitney form.
    Returns None when one class is absent (AUC undefined).
    """
    pos = [s for s, lab in zip(scores, labels) if lab == 1]   # events (deteriorated)
    neg = [s for s, lab in zip(scores, labels) if lab == 0]   # non-events
    if not pos or not neg:
        return None
    neg_sorted = sorted(neg)
    n_neg = len(neg_sorted)
    total = 0.0
    for s in pos:
        lo = bisect.bisect_left(neg_sorted, s)
        hi = bisect.bisect_right(neg_sorted, s)
        greater = n_neg - hi      # non-events with a HIGHER score → event ranked riskier ✓
        equal = hi - lo
        total += greater + 0.5 * equal
    return total / (len(pos) * n_neg)


def gini(scores: List[float], labels: List[int]) -> Optional[float]:
    """Accuracy Ratio (Gini) = 2·AUC − 1. 1 = perfect, 0 = random, <0 = inverted."""
    a = auc_low_score_risk(scores, labels)
    return None if a is None else 2.0 * a - 1.0


def gini_bootstrap_ci(
    scores: List[float], labels: List[int], n_boot: int = 1000,
    seed: int = 42, alpha: float = 0.05,
) -> Tuple[Optional[float], Optional[float], Optional[float]]:
    """Point Gini + (lo, hi) percentile bootstrap CI. Seeded → reproducible."""
    base = gini(scores, labels)
    if base is None:
        return base, None, None
    rng = random.Random(seed)
    m = len(scores)
    idx = range(m)
    vals: List[float] = []
    for _ in range(n_boot):
        sample = [rng.choice(idx) for _ in range(m)]
        g = gini([scores[i] for i in sample], [labels[i] for i in sample])
        if g is not None:
            vals.append(g)
    if not vals:
        return base, None, None
    vals.sort()
    lo = vals[max(0, int((alpha / 2) * len(vals)))]
    hi = vals[min(len(vals) - 1, int((1 - alpha / 2) * len(vals)))]
    return base, lo, hi


def deterioration_rate_by_tier(
    tiers: List[str], labels: List[int], tier_order: List[str],
) -> Tuple[List[Dict], bool]:
    """Realized deterioration rate per tier, ordered best→worst.

    Returns (rows, monotonic) where each row is
    ``{tier, n, events, rate}`` and *monotonic* is True when the rate is
    non-decreasing as the tier worsens (the discrimination we want to see).
    """
    agg: Dict[str, List[int]] = {}
    for t, lab in zip(tiers, labels):
        a = agg.setdefault(t, [0, 0])
        a[0] += 1
        a[1] += int(lab)
    rows: List[Dict] = []
    for tier in tier_order:
        if tier in agg:
            n, ev = agg[tier]
            rows.append({"tier": tier, "n": n, "events": ev, "rate": ev / n if n else None})
    rates = [r["rate"] for r in rows if r["rate"] is not None]
    monotonic = all(rates[i] <= rates[i + 1] + 1e-9 for i in range(len(rates) - 1))
    return rows, monotonic
