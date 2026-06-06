"""SDQ Macro-Political Risk Index (IRMP) — thin wrapper over the shared engine.

The scoring pipeline now lives in ``shared/indices``; this module binds it to the
IRMP config and remaps the generic output keys to the IRMP-specific contract
(``irmp_score``, ``risk_band``, ``country_code``) that the API and persistence
layer expect.
"""
import logging
from typing import Any, Dict

from shared.indices import run_index
from shared.indices.dimensions import Dataset as RegionalDataset
from modules.macro_political_risk.scoring.weights import IRMP_CONFIG

logger = logging.getLogger("sdq.macro_political_risk.engine")

MODEL_VERSION = "1.0"


def run_irmp(country_code: str, dataset: RegionalDataset) -> Dict[str, Any]:
    """Full deterministic IRMP pipeline for one country.

    Args:
        country_code: ISO code present as a key in *dataset* (e.g. "DO").
        dataset: ``{country_code: {variable: value}}`` for the regional peer set.

    Returns the IRMP breakdown (overall score, risk band, color and per-dimension
    detail) — directionally "higher = lower risk".
    """
    result = run_index(country_code, dataset, IRMP_CONFIG)
    return {
        "country_code": result["entity_key"],
        "irmp_score": result["score"],
        "risk_band": result["band"],
        "band_color": result["band_color"],
        "dimensions": result["dimensions"],
        "peer_set_size": result["peer_set_size"],
        "model_type": result["model_type"],
        "model_version": result["model_version"],
    }
