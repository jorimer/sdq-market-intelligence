"""Multidimensional development index (Eje 5).

Doctrine §7: well-being is multidimensional (Sen) and *distribution > average*
(Deaton/Piketty).  The composite per entity (region/group) is computed with the
shared index engine; we also report the distribution across entities so the
analyst never reads only the mean.
"""
import statistics
from typing import Dict, List

from shared.doctrine import load_doctrine
from shared.indices import run_index
from shared.indices.dimensions import Dataset

IDM_CONFIG = load_doctrine("social")


def compute_development(entity_key: str, dataset: Dataset) -> Dict:
    """Compute the development index for *entity_key* against the peer set."""
    result = run_index(entity_key, dataset, IDM_CONFIG)
    return {
        "entity_key": result["entity_key"],
        "development_score": result["score"],
        "band": result["band"],
        "band_color": result["band_color"],
        "dimensions": result["dimensions"],
        "model_version": result["model_version"],
    }


def distribution_stats(scores: List[float]) -> Dict:
    """Summarize a set of scores: mean AND spread (distribution > average)."""
    clean = [s for s in scores if s is not None]
    if not clean:
        return {"n": 0, "mean": None, "min": None, "max": None,
                "spread": None, "cv": None}
    mean = round(statistics.mean(clean), 2)
    lo, hi = round(min(clean), 2), round(max(clean), 2)
    spread = round(hi - lo, 2)
    # Coefficient of variation as a simple inequality read.
    cv = round(statistics.pstdev(clean) / mean, 4) if mean else None
    return {"n": len(clean), "mean": mean, "min": lo, "max": hi,
            "spread": spread, "cv": cv}
