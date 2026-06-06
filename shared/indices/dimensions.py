"""Per-dimension computation for any index.

Each dimension score is the simple mean of its regionally-normalized variables.
Missing variables are skipped (never interpolated) — consistent with the
platform rule of not inventing data.  Each result carries a full per-variable
breakdown so an analyst can reconstruct the number by hand.
"""
from typing import Dict, List

from shared.indices.config import IndexConfig
from shared.indices.normalization import normalize_variable

# dataset: {entity_key: {variable: value}}  (entity_key = country / sector / bank …)
Dataset = Dict[str, Dict[str, float]]


def compute_dimension(
    dimension: str, entity_key: str, dataset: Dataset, config: IndexConfig
) -> Dict:
    """Compute one dimension score for *entity_key* against *dataset*.

    Returns ``{"score": float, "variables": {var: {raw, normalized, inverted}}}``.
    """
    entity_values = dataset.get(entity_key, {})
    breakdown: Dict[str, Dict] = {}
    normalized_scores: List[float] = []

    for var in config.dimension_variables[dimension]:
        raw = entity_values.get(var)
        if raw is None:
            continue  # skip missing — no interpolation
        regional = [d[var] for d in dataset.values() if d.get(var) is not None]
        if not regional:
            continue
        invert = var in config.risk_increasing
        norm = normalize_variable(raw, regional, invert)
        breakdown[var] = {"raw": float(raw), "normalized": norm, "inverted": invert}
        normalized_scores.append(norm)

    score = round(sum(normalized_scores) / len(normalized_scores), 2) if normalized_scores else 0.0
    return {"score": score, "variables": breakdown}


def compute_all_dimensions(entity_key: str, dataset: Dataset, config: IndexConfig) -> Dict[str, Dict]:
    """Compute every dimension declared by *config* for *entity_key*."""
    return {
        dim: compute_dimension(dim, entity_key, dataset, config)
        for dim in config.dimension_weights
    }
