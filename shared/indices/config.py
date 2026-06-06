"""Index configuration contract.

An :class:`IndexConfig` is the single source of truth for *one* composite index:
its dimensions and weights, the variables that feed each dimension, which
variables are risk-increasing (and therefore inverted), and the qualitative
bands.  Configs are usually loaded from versioned house doctrine
(``shared/doctrine``) so that a weight change is a doctrine PR, not a code edit.

All configs are deterministic and self-validating: a malformed config raises at
construction time, never at scoring time.
"""
from dataclasses import dataclass
from typing import Dict, FrozenSet, List, Tuple

_WEIGHT_SUM_TOLERANCE = 1e-6


@dataclass(frozen=True)
class Band:
    """A qualitative band: scores ``>= lower`` (and below the next band) map here."""

    name: str
    lower: float          # inclusive lower bound on the 0-100 scale
    color: str            # hex color for UI ("#047857")


@dataclass(frozen=True)
class IndexConfig:
    """Declarative definition of one explainable composite index."""

    name: str
    dimension_weights: Dict[str, float]
    dimension_variables: Dict[str, List[str]]
    risk_increasing: FrozenSet[str]
    bands: Tuple[Band, ...]                      # ordered descending by ``lower``
    direction: str = "mayor score = mejor"

    def __post_init__(self) -> None:
        # Weights must sum to 1.0
        total = round(sum(self.dimension_weights.values()), 6)
        if abs(total - 1.0) > _WEIGHT_SUM_TOLERANCE:
            raise ValueError(
                f"{self.name}: los pesos de dimensión suman {total}, deben sumar 1.0"
            )
        # Every weighted dimension must declare variables (and vice versa)
        if set(self.dimension_weights) != set(self.dimension_variables):
            raise ValueError(
                f"{self.name}: las dimensiones con peso no coinciden con las que "
                f"declaran variables ({set(self.dimension_weights)} vs "
                f"{set(self.dimension_variables)})"
            )
        # Bands: at least one, ordered strictly descending by lower bound,
        # gap-free coverage of [0, 100].
        if not self.bands:
            raise ValueError(f"{self.name}: se requiere al menos una banda")
        lowers = [b.lower for b in self.bands]
        if lowers != sorted(lowers, reverse=True):
            raise ValueError(
                f"{self.name}: las bandas deben ir descendentes por 'lower'"
            )
        if len(set(lowers)) != len(lowers):
            raise ValueError(f"{self.name}: hay bandas con el mismo 'lower'")
        if min(lowers) != 0.0:
            raise ValueError(
                f"{self.name}: la banda inferior debe empezar en 0 (cobertura completa)"
            )

    @property
    def variable_order(self) -> List[str]:
        """Flat, dimension-ordered variable list (for ML feature vectors/exports)."""
        return [v for dim in self.dimension_weights for v in self.dimension_variables[dim]]
