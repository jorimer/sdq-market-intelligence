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


def auc_estratificado(
    scores: List[float], labels: List[int], strata: List[str],
) -> Tuple[Optional[float], int]:
    """AUC contando SOLO los pares que comparten estrato, y cuántos pares quedaron.

    Existe para separar dos cosas que el AUC agrupado suma sin distinguir: si el score
    ordena mal DENTRO de cada grupo, o si ordena bien dentro de todos y el signo lo produce
    la diferencia ENTRE grupos (Simpson). Un par formado por una entidad de cambio y un
    banco múltiple no informa sobre el ordenamiento: son poblaciones distintas puestas en la
    misma bolsa, y es justo el par que el AUC agrupado cuenta.

    Es el promedio de los AUC por estrato ponderado por sus pares (evento × no-evento), que
    es el AUC condicional exacto. Devuelve ``(None, 0)`` cuando ningún estrato tiene las dos
    clases: sin pares comparables no hay ordenamiento que medir, y eso se declara.
    """
    por_estrato: Dict[str, Tuple[List[float], List[int]]] = {}
    for s, lab, est in zip(scores, labels, strata):
        xs, ys = por_estrato.setdefault(est, ([], []))
        xs.append(s)
        ys.append(lab)
    numerador = 0.0
    pares = 0
    for xs, ys in por_estrato.values():
        n_pos = sum(ys)
        n_neg = len(ys) - n_pos
        if n_pos == 0 or n_neg == 0:
            continue  # sin las dos clases el estrato no aporta pares comparables
        a = auc_low_score_risk(xs, ys)
        if a is None:
            continue
        peso = n_pos * n_neg
        numerador += a * peso
        pares += peso
    return (None, 0) if pares == 0 else (numerador / pares, pares)


def gini_estratificado_bootstrap_ci(
    scores: List[float], labels: List[int], strata: List[str],
    n_boot: int = 1000, seed: int = 42, alpha: float = 0.05,
) -> Tuple[Optional[float], Optional[float], Optional[float], int]:
    """Gini dentro del estrato + IC bootstrap + nº de pares comparables.

    El remuestreo es sobre las observaciones (no dentro de cada estrato) para que el IC
    también cargue la incertidumbre de la composición del panel, que es lo que está en
    discusión.
    """
    a, pares = auc_estratificado(scores, labels, strata)
    if a is None:
        return None, None, None, 0
    base = 2.0 * a - 1.0
    rng = random.Random(seed)
    m = len(scores)
    idx = range(m)
    vals: List[float] = []
    for _ in range(n_boot):
        sample = [rng.choice(idx) for _ in range(m)]
        aa, _p = auc_estratificado(
            [scores[i] for i in sample], [labels[i] for i in sample],
            [strata[i] for i in sample],
        )
        if aa is not None:
            vals.append(2.0 * aa - 1.0)
    if not vals:
        return base, None, None, pares
    vals.sort()
    lo = vals[max(0, int((alpha / 2) * len(vals)))]
    hi = vals[min(len(vals) - 1, int((1 - alpha / 2) * len(vals)))]
    return base, lo, hi, pares


def _rangos(valores: List[float]) -> List[float]:
    """Rangos con empates promediados (el que Spearman necesita)."""
    orden = sorted(range(len(valores)), key=lambda i: valores[i])
    rangos = [0.0] * len(valores)
    i = 0
    while i < len(orden):
        j = i
        while j + 1 < len(orden) and valores[orden[j + 1]] == valores[orden[i]]:
            j += 1
        promedio = (i + j) / 2.0 + 1.0
        for k in range(i, j + 1):
            rangos[orden[k]] = promedio
        i = j + 1
    return rangos


def spearman(xs: List[float], ys: List[float]) -> Optional[float]:
    """Correlación de rangos. ``None`` con menos de 3 pares o con una serie constante."""
    if len(xs) != len(ys) or len(xs) < 3:
        return None
    rx, ry = _rangos(xs), _rangos(ys)
    n = len(rx)
    mx, my = sum(rx) / n, sum(ry) / n
    num = sum((a - mx) * (b - my) for a, b in zip(rx, ry))
    dx = sum((a - mx) ** 2 for a in rx)
    dy = sum((b - my) ** 2 for b in ry)
    if dx <= 0 or dy <= 0:
        return None
    return num / (dx ** 0.5 * dy ** 0.5)
