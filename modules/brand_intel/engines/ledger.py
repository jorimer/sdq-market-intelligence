"""Decision ledger — the accountability loop.

**The subject is the client and its decisions**, never the research provider. A decision
may originate in the tracker, the agency or the operation; what the ledger cares about is
that someone committed to a movement and that the next wave says whether it happened.

Five fields are mandatory: metric, baseline, evaluation window, success threshold and
owner. The threshold does the real work. Before any budget is committed, the ledger checks
the intended movement against the smallest movement the target wave's base can actually
detect. When the target sits under that floor, the decision is **unevaluable**: no wave
will ever be able to confirm or deny it. Better to learn that while redesigning the
decision than after paying for it.

That check is also the cheapest guard against a whole class of waste — the recommendation
phrased so broadly ("modernise the experience", "strengthen the connection") that no metric
could ever settle it.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import List, Optional

from modules.brand_intel.engines.significance import (
    MIN_PUBLISHABLE_BASE,
    NOT_DETECTABLE,
    assess_change,
    detectable_threshold,
)

# Ledger statuses
OPEN = "open"
ACHIEVED = "achieved"
WORSENED = "worsened"
INCONCLUSIVE = "not_detectable"
UNEVALUABLE = "unevaluable"


@dataclass(frozen=True)
class FeasibilityCheck:
    """Whether a decision can be evaluated at all, before it is committed."""

    feasible: bool
    detectable_threshold: Optional[float]
    reason: str


def check_feasibility(
    metric_code: str,
    baseline_value: Optional[float],
    expected_base_n: Optional[int],
    success_threshold: Optional[float],
) -> FeasibilityCheck:
    """Compare the intended movement against what the wave can detect."""
    if baseline_value is None:
        return FeasibilityCheck(False, None, "Sin línea base: la decisión no es medible.")
    if success_threshold is None or success_threshold <= 0:
        return FeasibilityCheck(
            False, None,
            "Sin umbral de éxito declarado: no hay contra qué emitir veredicto.",
        )
    if not expected_base_n or expected_base_n < MIN_PUBLISHABLE_BASE:
        return FeasibilityCheck(
            False, None,
            f"Base esperada insuficiente (n={expected_base_n or 0} < "
            f"{MIN_PUBLISHABLE_BASE}): ninguna ola podrá confirmarla.",
        )

    mdd = detectable_threshold(
        baseline_value, expected_base_n, baseline_value, expected_base_n
    )
    if mdd is None:
        return FeasibilityCheck(False, None, "No se pudo calcular el umbral detectable.")

    if success_threshold < mdd:
        return FeasibilityCheck(
            False, mdd,
            f"El movimiento esperado ({success_threshold:.1f} pp) es MENOR que el mínimo "
            f"detectable con esa base (±{mdd:.1f} pp). La decisión es inevaluable: "
            "hay que redimensionarla o cambiar el instrumento antes de gastar en ella.",
        )

    return FeasibilityCheck(
        True, mdd,
        f"Evaluable: el movimiento esperado ({success_threshold:.1f} pp) supera el mínimo "
        f"detectable (±{mdd:.1f} pp).",
    )


@dataclass(frozen=True)
class Verdict:
    status: str
    observed_delta: Optional[float]
    detectable_threshold: Optional[float]
    note: str


def evaluate(
    metric_code: str,
    baseline_value: Optional[float],
    baseline_base_n: Optional[int],
    target_value: Optional[float],
    target_base_n: Optional[int],
    higher_is_better: bool = True,
) -> Verdict:
    """Issue the verdict once the target wave has landed."""
    if target_value is None:
        return Verdict(OPEN, None, None, "La ola de evaluación aún no tiene dato.")

    a = assess_change(metric_code, baseline_value, baseline_base_n,
                      target_value, target_base_n)

    if a.verdict in ("unscoreable", "base_insufficient"):
        return Verdict(UNEVALUABLE, a.delta, a.threshold, a.note)

    if not a.is_finding:
        # Covers both 'not_detectable' and the explicit 'marginal' edge case: neither
        # licenses claiming the decision worked.
        prefix = ("Movimiento en el filo del umbral. " if a.verdict != NOT_DETECTABLE else "")
        return Verdict(INCONCLUSIVE, a.delta, a.threshold, prefix + a.note)

    improved = (a.delta > 0) if higher_is_better else (a.delta < 0)
    status = ACHIEVED if improved else WORSENED
    return Verdict(status, a.delta, a.threshold, a.note)


def summarize(verdicts: List[Verdict]) -> dict:
    """Roll-up for the report: how the quarter's committed decisions actually landed."""
    total = len(verdicts)
    counts = {ACHIEVED: 0, WORSENED: 0, INCONCLUSIVE: 0, UNEVALUABLE: 0, OPEN: 0}
    for v in verdicts:
        counts[v.status] = counts.get(v.status, 0) + 1
    return {
        "total": total,
        "achieved": counts[ACHIEVED],
        "worsened": counts[WORSENED],
        "inconclusive": counts[INCONCLUSIVE],
        "unevaluable": counts[UNEVALUABLE],
        "open": counts[OPEN],
        "closed": total - counts[OPEN],
    }
