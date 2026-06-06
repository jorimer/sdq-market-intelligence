"""IRMP per-dimension computation — delegates to the shared index engine.

Binds the generic ``shared/indices`` dimension functions to the IRMP config so
existing call sites (``compute_dimension(dim, cc, ds)``) keep their signature.
"""
from typing import Dict

from shared.indices import dimensions as _generic
from modules.macro_political_risk.scoring.weights import IRMP_CONFIG

# regional_dataset: {country_code: {variable: value}}
RegionalDataset = Dict[str, Dict[str, float]]


def compute_dimension(dimension: str, country_code: str, dataset: RegionalDataset) -> Dict:
    """Compute one IRMP dimension for *country_code* against *dataset*."""
    return _generic.compute_dimension(dimension, country_code, dataset, IRMP_CONFIG)


def compute_all_dimensions(country_code: str, dataset: RegionalDataset) -> Dict[str, Dict]:
    """Compute all IRMP dimensions for *country_code*."""
    return _generic.compute_all_dimensions(country_code, dataset, IRMP_CONFIG)
