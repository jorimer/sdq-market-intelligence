"""ESG / climate exposure scoring (Eje 7).

Doctrine §9: financial materiality > formal compliance; demand a metric (penalize
greenwashing); adjust to Caribbean vulnerability.  The composite per sector is
computed with the shared index engine (higher = lower exposure / better managed);
a materiality flag marks sectors where exposure is high but governance is weak.
"""
from typing import Dict

from shared.doctrine import load_doctrine
from shared.indices import run_index
from shared.indices.dimensions import Dataset

IRC_CONFIG = load_doctrine("esg")

# Materiality thresholds (on the 0-100 resilience score; lower = more exposed).
_MATERIAL_SCORE = 50.0
_WEAK_GOVERNANCE = 50.0


def _materiality(score: float, governance_score: float) -> Dict:
    """Flag financial materiality: high exposure + weak governance = material risk."""
    material = score < _MATERIAL_SCORE
    greenwashing_flag = material and governance_score >= 70.0  # buena narrativa, alta exposición
    if score < _MATERIAL_SCORE and governance_score < _WEAK_GOVERNANCE:
        level = "alta"
    elif material:
        level = "media"
    else:
        level = "baja"
    return {
        "material": material,
        "level": level,
        "greenwashing_watch": greenwashing_flag,
    }


def compute_exposure(sector_key: str, dataset: Dataset) -> Dict:
    """Compute the ESG/climate resilience score + materiality for *sector_key*."""
    result = run_index(sector_key, dataset, IRC_CONFIG)
    gov = result["dimensions"].get("governance", {}).get("score", 50.0)
    return {
        "sector_key": result["entity_key"],
        "esg_score": result["score"],
        "band": result["band"],
        "band_color": result["band_color"],
        "dimensions": result["dimensions"],
        "materiality": _materiality(result["score"], gov),
        "model_version": result["model_version"],
    }
