"""Generic deterministic index engine.

DB-agnostic: operates on a plain in-memory dataset and returns dicts.
Persistence and event publishing happen in each module's API/service layer.

Pipeline:
    1. Normalize each variable against the peer set.
    2. Average normalized variables into per-dimension scores.
    3. Weighted-sum dimensions into the overall score (0-100), clamped.
    4. Map to a qualitative band and emit an auditable breakdown.
"""
import logging
from typing import Any, Dict

from shared.indices.bands import get_band_color, map_band
from shared.indices.config import IndexConfig
from shared.indices.dimensions import Dataset, compute_all_dimensions

logger = logging.getLogger("sdq.indices.engine")

MODEL_VERSION = "1.0"


def _clamp(value: float, lo: float = 0.0, hi: float = 100.0) -> float:
    return max(lo, min(hi, value))


def run_index(entity_key: str, dataset: Dataset, config: IndexConfig) -> Dict[str, Any]:
    """Full deterministic pipeline for one entity under *config*.

    Args:
        entity_key: key present in *dataset* (e.g. "DO", a sector id, a bank id).
        dataset: ``{entity_key: {variable: value}}`` for the peer set.
        config: the index definition.

    Returns a breakdown with the overall score, band, color, and per-dimension
    (and per-variable) detail needed for explainability.
    """
    if entity_key not in dataset:
        raise KeyError(f"'{entity_key}' no está en el conjunto de datos")

    dimensions = compute_all_dimensions(entity_key, dataset, config)

    overall = sum(
        dimensions[dim]["score"] * weight
        for dim, weight in config.dimension_weights.items()
    )
    overall = round(_clamp(overall), 2)
    band = map_band(overall, config.bands)

    return {
        "entity_key": entity_key,
        "index": config.name,
        "score": overall,
        "band": band,
        "band_color": get_band_color(band, config.bands),
        "dimensions": {
            dim: {
                "score": dimensions[dim]["score"],
                "weight": config.dimension_weights[dim],
                "contribution": round(dimensions[dim]["score"] * config.dimension_weights[dim], 2),
                "variables": dimensions[dim]["variables"],
            }
            for dim in config.dimension_weights
        },
        "peer_set_size": len(dataset),
        "model_type": "deterministic",
        "model_version": MODEL_VERSION,
        "direction": config.direction,
    }
