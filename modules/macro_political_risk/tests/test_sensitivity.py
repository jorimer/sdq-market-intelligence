"""Weight-sensitivity check for the IRMP (±10% per dimension).

Acceptance criterion (SPEC §8): perturbing dimension weights by ±10% must not
destabilize the index — scores should move modestly and the relative ordering of
peers should hold.  This guards against an index that is brittle to its weights.
"""
from dataclasses import replace

from shared.indices import IndexConfig, run_index
from modules.macro_political_risk.scoring.weights import IRMP_CONFIG

DATASET = {
    "DO": {"gdp_cagr_3y": 5.0, "public_debt_gdp": 45.0, "wgi_rule_of_law": 55.0,
           "fx_volatility": 3.0, "news_sentiment": 20.0, "discretion": 30.0},
    "CR": {"gdp_cagr_3y": 3.0, "public_debt_gdp": 63.0, "wgi_rule_of_law": 65.0,
           "fx_volatility": 5.0, "news_sentiment": 10.0, "discretion": 40.0},
    "PA": {"gdp_cagr_3y": 1.0, "public_debt_gdp": 52.0, "wgi_rule_of_law": 50.0,
           "fx_volatility": 8.0, "news_sentiment": -10.0, "discretion": 60.0},
}


def _perturbed(dimension: str, factor: float) -> IndexConfig:
    """IRMP config with *dimension* weight scaled by *factor*, renormalized to 1.0."""
    weights = dict(IRMP_CONFIG.dimension_weights)
    weights[dimension] *= factor
    total = sum(weights.values())
    weights = {k: round(v / total, 6) for k, v in weights.items()}
    # Fix rounding drift so the sum is exactly 1.0 (IndexConfig validates this).
    drift = round(1.0 - sum(weights.values()), 6)
    weights[dimension] = round(weights[dimension] + drift, 6)
    return replace(IRMP_CONFIG, dimension_weights=weights)


def test_score_moves_modestly_under_weight_perturbation():
    base = run_index("DO", DATASET, IRMP_CONFIG)["score"]
    for dim in IRMP_CONFIG.dimension_weights:
        for factor in (0.9, 1.1):
            score = run_index("DO", DATASET, _perturbed(dim, factor))["score"]
            assert abs(score - base) <= 5.0, (
                f"IRMP demasiado sensible a {dim} x{factor}: {score} vs base {base}"
            )


def test_peer_ordering_is_stable_under_perturbation():
    def ranking(config):
        scored = {c: run_index(c, DATASET, config)["score"] for c in DATASET}
        return sorted(scored, key=scored.get, reverse=True)

    base_order = ranking(IRMP_CONFIG)
    for dim in IRMP_CONFIG.dimension_weights:
        for factor in (0.9, 1.1):
            assert ranking(_perturbed(dim, factor)) == base_order
