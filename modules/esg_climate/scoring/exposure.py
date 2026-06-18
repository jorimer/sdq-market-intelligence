"""IRC — climate-resilience scoring (Eje 7), national.

Re-scoped 2026-06-18 from per-sector to per-COUNTRY: the composite per country is
computed with the shared index engine (higher = more resilient / less climate
risk), against the Caribbean/LatAm panel as the peer set. Doctrine in
``shared/doctrine/esg.yaml`` (v2.0).
"""
from typing import Dict

from shared.doctrine import load_doctrine
from shared.indices import run_index
from shared.indices.dimensions import Dataset

IRC_CONFIG = load_doctrine("esg")


def compute_irc(entity_key: str, dataset: Dataset) -> Dict:
    """Compute the climate-resilience (IRC) score for *entity_key* (a country)."""
    result = run_index(entity_key, dataset, IRC_CONFIG)
    return {
        "entity_key": result["entity_key"],
        "esg_score": result["score"],
        "band": result["band"],
        "band_color": result["band_color"],
        "dimensions": result["dimensions"],
        "model_version": result["model_version"],
    }
