"""Significance engine — the gate every other engine consults before asserting anything.

Two jobs:

1. **Confidence bands.** What range a measurement actually spans, given its base.
2. **Detectable movement (MDD).** The smallest wave-over-wave change that can sustain a
   decision. Below it, a movement is not a finding — it is sampling noise wearing one.

Design rules, applied without exception:

* **A base is never assumed.** An observation with no ``base_n`` is ``unscoreable``. It can
  be displayed, never used for a verdict.
* **Bases under 30 are not publishable.** Same floor the industry marks with an asterisk;
  here it is enforced rather than footnoted.
* **Only proportions get bands.** Double-indexation scores are ratios over a normalized
  total, not proportions of a base — handing them a binomial interval would manufacture
  confidence out of nothing (see ``metrics.MetricDef.supports_bands``).
* **The "edge" verdict is explicit.** A change that lands within 10% of its own threshold
  is reported as ``marginal``, not promoted to a finding. A difference that barely clears
  the bar should not, on its own, launch an expensive programme; it should trigger
  corroboration from an independent source.

Waves are treated as independent samples (fresh sample per wave, the standard tracking
design). With a panel design the variance of the difference would be lower and these
thresholds conservative.
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Optional, Tuple

from modules.brand_intel.engines.metrics import supports_bands

Z95 = 1.96
MIN_PUBLISHABLE_BASE = 30
EDGE_TOLERANCE = 0.10  # within 10% of the threshold → "marginal", never a headline

# Verdicts
SIGNIFICANT_UP = "significant_up"
SIGNIFICANT_DOWN = "significant_down"
MARGINAL = "marginal"
NOT_DETECTABLE = "not_detectable"
UNSCOREABLE = "unscoreable"
BASE_INSUFFICIENT = "base_insufficient"


def confidence_halfwidth(value: float, base_n: Optional[int], z: float = Z95) -> Optional[float]:
    """Half-width of the confidence interval for a proportion expressed in percent."""
    if base_n is None or base_n <= 0:
        return None
    p = value / 100.0
    if not 0.0 <= p <= 1.0:
        return None
    return z * math.sqrt(p * (1.0 - p) / base_n) * 100.0


def confidence_interval(
    value: float, base_n: Optional[int], z: float = Z95
) -> Optional[Tuple[float, float]]:
    hw = confidence_halfwidth(value, base_n, z)
    if hw is None:
        return None
    return (value - hw, value + hw)


def detectable_threshold(
    v1: float, n1: Optional[int], v2: float, n2: Optional[int], z: float = Z95
) -> Optional[float]:
    """Minimum detectable difference between two independent proportions, in pp."""
    if not n1 or not n2 or n1 <= 0 or n2 <= 0:
        return None
    p1, p2 = v1 / 100.0, v2 / 100.0
    if not (0.0 <= p1 <= 1.0 and 0.0 <= p2 <= 1.0):
        return None
    se = math.sqrt(p1 * (1.0 - p1) / n1 + p2 * (1.0 - p2) / n2)
    return z * se * 100.0


@dataclass(frozen=True)
class ChangeAssessment:
    """The verdict on a wave-over-wave movement, with everything needed to defend it."""

    delta: Optional[float]
    threshold: Optional[float]
    verdict: str
    publishable: bool
    note: str

    @property
    def is_finding(self) -> bool:
        """Only a clean significant move counts as a finding. 'Marginal' does not."""
        return self.verdict in (SIGNIFICANT_UP, SIGNIFICANT_DOWN)


def assess_change(
    metric_code: str,
    prev_value: Optional[float],
    prev_base: Optional[int],
    curr_value: Optional[float],
    curr_base: Optional[int],
) -> ChangeAssessment:
    """Classify a movement between two waves for one metric/brand/segment cell."""
    if prev_value is None or curr_value is None:
        return ChangeAssessment(None, None, UNSCOREABLE, False,
                                "Falta una de las dos observaciones.")

    delta = curr_value - prev_value

    if not supports_bands(metric_code):
        return ChangeAssessment(
            delta, None, UNSCOREABLE, True,
            "Métrica de índice: no admite banda de confianza; se lee como perfil, "
            "no como proporción de una base.",
        )

    if prev_base is None or curr_base is None:
        return ChangeAssessment(
            delta, None, UNSCOREABLE, False,
            "Sin base declarada: el movimiento no puede sostener un veredicto.",
        )

    if min(prev_base, curr_base) < MIN_PUBLISHABLE_BASE:
        return ChangeAssessment(
            delta, None, BASE_INSUFFICIENT, False,
            f"Base insuficiente (n={min(prev_base, curr_base)} < {MIN_PUBLISHABLE_BASE}): "
            "no publicable.",
        )

    thr = detectable_threshold(prev_value, prev_base, curr_value, curr_base)
    if thr is None:
        return ChangeAssessment(delta, None, UNSCOREABLE, False,
                                "No se pudo calcular el umbral.")

    a_delta = abs(delta)
    if a_delta >= thr * (1.0 + EDGE_TOLERANCE):
        verdict = SIGNIFICANT_UP if delta > 0 else SIGNIFICANT_DOWN
        note = f"Movimiento de {delta:+.1f} pp sobre un umbral de ±{thr:.1f} pp."
    elif a_delta >= thr * (1.0 - EDGE_TOLERANCE):
        verdict = MARGINAL
        note = (f"Movimiento de {delta:+.1f} pp contra un umbral de ±{thr:.1f} pp: "
                "en el filo. Requiere corroboración independiente antes de accionar.")
    else:
        verdict = NOT_DETECTABLE
        note = (f"Movimiento de {delta:+.1f} pp por debajo del umbral de ±{thr:.1f} pp: "
                "no distinguible de ruido muestral.")

    return ChangeAssessment(delta, thr, verdict, True, note)


def signal_filter_row(
    metric_code: str, value: float, base_n: Optional[int]
) -> dict:
    """One row of the signal filter: what this cell would need to move to matter.

    Uses the same value on both sides — the threshold a *future* wave of comparable size
    must clear. This is the priorisation tool the brand team gets: with 59 charts in hand,
    it says which movements can carry a budget decision at all.
    """
    publishable = bool(base_n and base_n >= MIN_PUBLISHABLE_BASE)
    thr = (detectable_threshold(value, base_n, value, base_n)
           if publishable and supports_bands(metric_code) else None)
    return {
        "metric_code": metric_code,
        "value": value,
        "base_n": base_n,
        "threshold": thr,
        "publishable": publishable,
        "note": ("" if publishable else
                 f"Base menor a {MIN_PUBLISHABLE_BASE}: no sostiene lectura."),
    }
