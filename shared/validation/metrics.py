"""Discrimination metrics for any score backtest (Gini/AR, tier curve).

Promoted from banking_score/validation so every axis (rating, IRMP, …) shares one
implementation. Convention: LOWER score = riskier (more likely label==1).

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


def _avg_ranks(xs: List[float]) -> List[float]:
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


def spearman(xs: List[float], ys: List[float]) -> Optional[float]:
    """Spearman rank correlation (ρ); None if n<3 or no variance."""
    n = len(xs)
    if n < 3:
        return None
    rx, ry = _avg_ranks(xs), _avg_ranks(ys)
    mx, my = sum(rx) / n, sum(ry) / n
    cov = sum((a - mx) * (b - my) for a, b in zip(rx, ry))
    vx = sum((a - mx) ** 2 for a in rx)
    vy = sum((b - my) ** 2 for b in ry)
    if vx <= 0 or vy <= 0:
        return None
    return cov / (vx * vy) ** 0.5


def spearman_bootstrap_ci(
    xs: List[float], ys: List[float], n_boot: int = 1000,
    seed: int = 42, alpha: float = 0.05,
) -> Tuple[Optional[float], Optional[float], Optional[float]]:
    """Point Spearman ρ + (lo, hi) percentile bootstrap CI. Seeded → reproducible.

    Used for convergent validity (e.g. an index's regional ranking vs an external
    reference index). With a small n the CI is wide — that honesty is the point."""
    base = spearman(xs, ys)
    if base is None:
        return base, None, None
    rng = random.Random(seed)
    m = len(xs)
    idx = range(m)
    vals: List[float] = []
    for _ in range(n_boot):
        sample = [rng.choice(idx) for _ in range(m)]
        r = spearman([xs[i] for i in sample], [ys[i] for i in sample])
        if r is not None:
            vals.append(r)
    if not vals:
        return base, None, None
    vals.sort()
    lo = vals[max(0, int((alpha / 2) * len(vals)))]
    hi = vals[min(len(vals) - 1, int((1 - alpha / 2) * len(vals)))]
    return base, lo, hi


def mean_ic_with_t(yearly_ics: List[float], alpha: float = 0.05) -> Optional[Dict]:
    """Mean information coefficient + t-test over the series of yearly ICs.

    The defensible statistic for a sector×year panel: average the per-year
    cross-sectional rank IC and infer on the SERIES of ``k`` yearly ICs, instead of
    bootstrap-resampling the stacked pairs (which treats year/sector-clustered
    observations as independent and understates the CI). Inference uses Student's
    t with ``df = k-1`` — NOT the normal — because the small ``k`` is the whole point.

    Returns ``{mean_ic, n_years, sd, t_stat, ci_lo, ci_hi}`` or ``None`` if ``k < 2``
    (no series to infer on). With zero variance (all ICs equal) the t is undefined →
    ``t_stat`` is ``None`` and the CI collapses to the mean (disclosed, never crashes).
    """
    k = len(yearly_ics)
    if k < 2:
        return None
    mean = sum(yearly_ics) / k
    sd = (sum((x - mean) ** 2 for x in yearly_ics) / (k - 1)) ** 0.5  # sample sd (ddof=1)
    se = sd / (k ** 0.5)
    if se == 0:  # all yearly ICs identical → t undefined, CI is a point
        return {"mean_ic": round(mean, 3), "n_years": k, "sd": 0.0,
                "t_stat": None, "ci_lo": round(mean, 3), "ci_hi": round(mean, 3)}
    from scipy.stats import t as student_t  # scipy is a project dependency (requirements.txt)

    half = float(student_t.ppf(1 - alpha / 2, k - 1)) * se
    return {"mean_ic": round(mean, 3), "n_years": k, "sd": round(sd, 4),
            "t_stat": round(mean / se, 3),
            "ci_lo": round(mean - half, 3), "ci_hi": round(mean + half, 3)}


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


def monotonicity_violations(rows: List[Dict]) -> List[Dict]:
    """Pares consecutivos donde la tasa BAJA al empeorar el tier — la curva se da vuelta.

    Existe para que el caveat pueda NOMBRAR el defecto en vez de describirlo de memoria. El
    de banca decía «ruido muestral en tiers intermedios» y la anomalía estaba en la banda
    SUPERIOR con el N más grande del panel (Sólida, n=516, 23,1% de deterioro, por encima de
    Adecuada). Un Chief Economist lo ve en la primera lectura de la tabla; el caveat, no.

    Ordenadas por magnitud de la inversión: la primera es la que hay que explicar.
    """
    presentes = [r for r in rows if r.get("rate") is not None]
    fallos = []
    for mejor, peor in zip(presentes, presentes[1:]):
        if mejor["rate"] > peor["rate"] + 1e-9:
            fallos.append({
                "mejor": mejor["tier"], "mejor_n": mejor["n"], "mejor_rate": mejor["rate"],
                "peor": peor["tier"], "peor_n": peor["n"], "peor_rate": peor["rate"],
                "brecha": round(mejor["rate"] - peor["rate"], 4),
            })
    return sorted(fallos, key=lambda f: -f["brecha"])
