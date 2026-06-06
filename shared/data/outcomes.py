"""Labeled-outcome capture for backtesting.

The methodology requires validating scores against realized outcomes (rating
migrations, defaults, crises).  This is the minimal store for those labels so
later phases can backtest indices against what actually happened.  DB-agnostic:
records are plain dataclasses; persistence is layered per module.
"""
from dataclasses import dataclass
from datetime import date
from typing import Optional

from shared.data.lineage import Lineage


@dataclass(frozen=True)
class LabeledOutcome:
    """A realized outcome for an entity, used to validate a prior score."""

    entity_key: str             # bank id, country code, sector id …
    outcome_type: str           # "default", "rating_migration", "crisis", …
    label: str                  # the realized value/class (e.g. "downgrade", "1")
    observed_at: date           # when the outcome materialized
    lineage: Lineage
    score_at_prediction: Optional[float] = None  # the score we had emitted before
    note: Optional[str] = None
