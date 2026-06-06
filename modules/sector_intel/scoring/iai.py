"""IAI (Investment Attractiveness Index) — delegates to the shared index engine.

The IAI is a cross-sectional composite: sectors are normalized against the peer
set of sectors, then dimensions are weighted per house doctrine
(`shared/doctrine/sectoral.yaml`).  Per-sector weight recalibration (spec v2
matrix) overrides the base config when available.
"""
from typing import Dict

from shared.doctrine import load_doctrine
from shared.indices import run_index
from shared.indices.dimensions import Dataset

IAI_CONFIG = load_doctrine("sectoral")


def compute_iai(sector_code: str, dataset: Dataset) -> Dict:
    """Compute the IAI for *sector_code* against the sector peer set *dataset*."""
    result = run_index(sector_code, dataset, IAI_CONFIG)
    return {
        "sector_code": result["entity_key"],
        "iai_score": result["score"],
        "band": result["band"],
        "band_color": result["band_color"],
        "dimensions": result["dimensions"],
        "peer_set_size": result["peer_set_size"],
        "model_version": result["model_version"],
    }
