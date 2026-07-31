"""Forecast engine — a frozen prediction, and the discipline that makes it worth reading.

Mirrors the TPM model's ledger: issue a forecast BEFORE the data exists, score it when the
wave lands, never seed the past. The point is not the prediction — it is the filter. An
indicator that lands inside its band needs no meeting; one that falls outside does. That
turns a 59-chart deck into the two or three conversations the quarter actually justifies.

**The rule is selected by backtest, not by preference.** Three naive candidates compete on
the history available; the winner issues the forecast and the report names it. With a
handful of waves this is deliberately a naive baseline, never a learned model: there is no
panel to train on, and pretending otherwise is the overfitting this engine exists to
avoid. It earns its keep from wave ~8-10 onward, and the report says so.

An early empirical result worth carrying into the deliverable: on tracker series,
**trend extrapolation is the worst of the three rules**. These series are stationary with
sampling noise, so projecting their slope produces systematic error — which matters,
because reading each chart as a trend is the default habit these reports invite.
"""
from __future__ import annotations

from dataclasses import dataclass
from statistics import mean
from typing import Callable, Dict, List, Optional, Sequence

from modules.brand_intel.engines.significance import confidence_halfwidth


def rule_persistence(history: Sequence[float]) -> float:
    """Last observed value."""
    return history[-1]


def rule_mean(history: Sequence[float]) -> float:
    """Mean of all history."""
    return mean(history)


def rule_trend(history: Sequence[float]) -> float:
    """Last value plus the last step."""
    if len(history) < 2:
        return history[-1]
    return history[-1] + (history[-1] - history[-2])


RULES: Dict[str, Callable[[Sequence[float]], float]] = {
    "persistence": rule_persistence,
    "mean": rule_mean,
    "trend": rule_trend,
}

MIN_HISTORY = 2          # need at least two points to forecast the third
MIN_BACKTEST_POINTS = 1  # need at least one scored prediction to rank rules


@dataclass(frozen=True)
class BacktestResult:
    rule: str
    mae: Optional[float]
    n_predictions: int


@dataclass(frozen=True)
class Forecast:
    point: float
    lo: float
    hi: float
    rule: str
    basis: str


def backtest_rules(series: Sequence[float]) -> List[BacktestResult]:
    """Score every rule on the history, expanding window, and rank by error.

    Predicts each point from those strictly before it — no look-ahead. With N points there
    are N - MIN_HISTORY scored predictions.
    """
    results: List[BacktestResult] = []
    for name, fn in RULES.items():
        errors: List[float] = []
        for i in range(MIN_HISTORY, len(series)):
            errors.append(abs(fn(series[:i]) - series[i]))
        results.append(BacktestResult(name, mean(errors) if errors else None, len(errors)))
    results.sort(key=lambda r: (r.mae is None, r.mae if r.mae is not None else 0.0))
    return results


def select_rule(series: Sequence[float]) -> str:
    """Winning rule for this series, or persistence when history is too short to judge."""
    if len(series) < MIN_HISTORY + MIN_BACKTEST_POINTS:
        return "persistence"
    ranked = backtest_rules(series)
    best = ranked[0]
    return best.rule if best.mae is not None else "persistence"


def issue_forecast(
    series: Sequence[float],
    base_n: Optional[int],
    rule: Optional[str] = None,
) -> Optional[Forecast]:
    """Freeze a forecast for the next wave.

    The band is the sampling interval of the forecast point at the expected base: it is
    the range within which a result carries no news. Without a base there is no band, and
    the engine declines to issue rather than invent one.
    """
    usable = [v for v in series if v is not None]
    if len(usable) < MIN_HISTORY:
        return None

    chosen = rule or select_rule(usable)
    point = RULES[chosen](usable)
    point = max(0.0, min(100.0, point))

    hw = confidence_halfwidth(point, base_n)
    if hw is None:
        return None

    n_back = max(0, len(usable) - MIN_HISTORY)
    basis = (
        f"Regla '{chosen}' seleccionada por backtest sobre {n_back} "
        f"pronóstico{'s' if n_back != 1 else ''} · banda al 95% con base n={base_n}."
        if n_back else
        f"Regla '{chosen}' por defecto: historia insuficiente para backtest "
        f"· banda al 95% con base n={base_n}."
    )
    return Forecast(point, max(0.0, point - hw), min(100.0, point + hw), chosen, basis)


@dataclass(frozen=True)
class ForecastScore:
    actual: float
    point: float
    abs_error: float
    inside_band: bool
    note: str


def score_forecast(point: float, lo: float, hi: float, actual: float) -> ForecastScore:
    """Score a frozen forecast against the landed value."""
    inside = lo <= actual <= hi
    err = abs(actual - point)
    note = (
        f"Resultado {actual:.1f}% dentro de la banda [{lo:.1f}, {hi:.1f}]: "
        "sin novedad, no requiere discusión."
        if inside else
        f"Resultado {actual:.1f}% FUERA de la banda [{lo:.1f}, {hi:.1f}]: "
        "entra a la agenda del trimestre."
    )
    return ForecastScore(actual, point, err, inside, note)


def track_record(scores: Sequence[ForecastScore]) -> Optional[Dict[str, float]]:
    """Aggregate hit rate and error across scored forecasts — the model's live record."""
    if not scores:
        return None
    return {
        "n": len(scores),
        "hit_rate": sum(1 for s in scores if s.inside_band) / len(scores) * 100.0,
        "mae": mean(s.abs_error for s in scores),
    }
