"""Load versioned house doctrine into an :class:`IndexConfig`.

Doctrine lives as ``{axis}.yaml`` next to this module.  The loader is the only
bridge between the human-maintained doctrine and the scoring engine, so weight
changes flow doctrine → config → engine with no code edits.
"""
from functools import lru_cache
from pathlib import Path
from typing import Any, Dict, List

import yaml

from shared.indices.config import Band, IndexConfig

_DOCTRINE_DIR = Path(__file__).resolve().parent


def available_axes() -> List[str]:
    """List axis names that have a doctrine file (e.g. ``["regulatory"]``)."""
    return sorted(p.stem for p in _DOCTRINE_DIR.glob("*.yaml"))


@lru_cache(maxsize=None)
def load_doctrine_raw(axis: str) -> Dict[str, Any]:
    """Return the full parsed doctrine YAML for *axis* (beyond the IndexConfig).

    The scoring engine only needs weights/variables/bands (:func:`load_doctrine`),
    but some declared assumptions live alongside them in the same control
    document — e.g. ``inflation_targets`` for the IRMP. This exposes the raw dict
    so those assumptions stay in doctrine (PR-governed), not scattered in code.
    """
    path = _DOCTRINE_DIR / f"{axis}.yaml"
    if not path.exists():
        raise FileNotFoundError(
            f"No existe doctrina para el eje '{axis}' ({path.name}). "
            f"Ejes disponibles: {available_axes()}"
        )
    with path.open(encoding="utf-8") as fh:
        return yaml.safe_load(fh)


@lru_cache(maxsize=None)
def load_doctrine(axis: str) -> IndexConfig:
    """Load the doctrine for *axis* and return its validated ``IndexConfig``.

    Args:
        axis: doctrine file stem, e.g. ``"regulatory"`` → ``regulatory.yaml``.

    Raises:
        FileNotFoundError: if no doctrine file exists for *axis*.
        ValueError: if the doctrine is malformed (propagated from IndexConfig).
    """
    path = _DOCTRINE_DIR / f"{axis}.yaml"
    if not path.exists():
        raise FileNotFoundError(
            f"No existe doctrina para el eje '{axis}' ({path.name}). "
            f"Ejes disponibles: {available_axes()}"
        )

    with path.open(encoding="utf-8") as fh:
        raw = yaml.safe_load(fh)

    bands = tuple(
        Band(name=b["name"], lower=float(b["lower"]), color=b["color"])
        for b in raw["bands"]
    )
    return IndexConfig(
        name=raw["name"],
        dimension_weights={k: float(v) for k, v in raw["dimension_weights"].items()},
        dimension_variables={k: list(v) for k, v in raw["dimension_variables"].items()},
        risk_increasing=frozenset(raw.get("risk_increasing", [])),
        bands=bands,
        direction=raw.get("direction", "mayor score = mejor"),
    )
