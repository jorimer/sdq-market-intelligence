"""Feature extraction for XGBoost ML model.

Converts indicator scores from the scoring engine into the 21-dimensional
feature vector expected by the XGBClassifier.
"""
from typing import Dict, List

from modules.banking_score.scoring.weights import FEATURE_ORDER


def extract_feature_vector(indicator_scores: Dict[str, float]) -> List[float]:
    """Extract ordered 21-dim feature vector from indicator score dict.

    Args:
        indicator_scores: ``{indicator_name: score}`` — only the *score*
            field (0-100), not the raw value.

    Returns:
        List of 21 floats in the canonical order defined by ``FEATURE_ORDER``.

    >>> vec = extract_feature_vector({"solvencia": 85.0, "tier1_ratio": 90.0})
    >>> len(vec) == len(FEATURE_ORDER)
    True
    """
    return [indicator_scores.get(feat, 0.0) for feat in FEATURE_ORDER]


def scoring_result_to_features(scoring_result: Dict) -> List[float]:
    """Convert a full ``run_scoring()`` result dict into a feature vector.

    The scoring engine returns indicators as ``{name: {"raw": ..., "score": ...}}``.
    This helper extracts only the *score* values before building the vector.
    """
    indicators = scoring_result.get("indicators", {})
    flat = {}
    for name, val in indicators.items():
        if isinstance(val, dict):
            flat[name] = val.get("score", 0.0)
        else:
            flat[name] = float(val)
    return extract_feature_vector(flat)
