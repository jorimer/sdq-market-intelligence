"""Sub-component weights for the SDQ Banking Score methodology.

The overall score is a weighted average of 5 sub-components:
  Solidez Financiera: 40%   — Capital adequacy and leverage
  Calidad de Activos: 30%   — Portfolio quality and concentration
  Eficiencia y Rentab: 15%  — Return and cost efficiency
  Liquidez: 10%             — Short-term and structural liquidity
  Diversificación: 5%       — Income diversification
"""

SUB_COMPONENT_WEIGHTS = {
    "solidez": 0.40,
    "calidad": 0.30,
    "eficiencia": 0.15,
    "liquidez": 0.10,
    "diversificacion": 0.05,
}

# ── Weight profiles per entity_type (same framework, recalibrated) ──
#
# The 5 sub-components are universal; their relative weight is recalibrated by
# entity type (SPEC §3): AAyP are mortgage-intensive (asset quality matters more),
# corporaciones/cambiarias are smaller and liquidity/solidity-sensitive, etc.
# Every profile must sum to 1.0.  Unknown types fall back to the base weights.

WEIGHT_PROFILES = {
    # Banca múltiple — base methodology.
    "banca_multiple": dict(SUB_COMPONENT_WEIGHTS),
    # Asociaciones de Ahorros y Préstamos — mortgage-intensive → asset quality up.
    "aap": {
        "solidez": 0.38, "calidad": 0.34, "eficiencia": 0.13,
        "liquidez": 0.10, "diversificacion": 0.05,
    },
    # Bancos de ahorro y crédito — smaller, funding-sensitive → liquidity up.
    "banco_ahorro_credito": {
        "solidez": 0.40, "calidad": 0.28, "eficiencia": 0.14,
        "liquidez": 0.13, "diversificacion": 0.05,
    },
    # Corporaciones de crédito — small, capital-sensitive → solidity up.
    "corporacion_credito": {
        "solidez": 0.45, "calidad": 0.28, "eficiencia": 0.13,
        "liquidez": 0.10, "diversificacion": 0.04,
    },
    # Intermediación cambiaria — liquidity/operational, less of a credit book.
    "cambiaria": {
        "solidez": 0.35, "calidad": 0.20, "eficiencia": 0.20,
        "liquidez": 0.20, "diversificacion": 0.05,
    },
    # Fiduciarias — fee-based service companies. Income diversification (HHI) is
    # structurally ~0 for ALL of them (mono-line: ~100% comisiones fiduciarias), so it
    # doesn't discriminate — its weight is trimmed (0.10→0.05) and redistributed to the
    # dimensions that do (solidez/calidad/eficiencia). v1.1 calibration (2026-06-11).
    "fiduciaria": {
        "solidez": 0.37, "calidad": 0.22, "eficiencia": 0.26,
        "liquidez": 0.10, "diversificacion": 0.05,
    },
}


def get_sub_component_weights(entity_type=None) -> dict:
    """Return the sub-component weight profile for *entity_type* (base if unknown)."""
    if entity_type is None:
        return dict(SUB_COMPONENT_WEIGHTS)
    return dict(WEIGHT_PROFILES.get(entity_type, SUB_COMPONENT_WEIGHTS))


# Indicator groupings by sub-component
SOLIDEZ_INDICATORS = [
    "solvencia", "tier1_ratio", "leverage",
    "cobertura_provisiones", "patrimonio_activos",
]

CALIDAD_INDICATORS = [
    "morosidad", "pct_cartera_a", "concentracion_top10",
    "hhi_sectorial", "castigos_pct", "exposicion_re",
    "migracion", "composite_calidad",
]

EFICIENCIA_INDICATORS = ["roa", "roe", "margen_financiero", "cost_to_income"]

LIQUIDEZ_INDICATORS = ["liquidez_inmediata", "ltd", "liquidez_ajustada"]

DIVERSIFICACION_INDICATORS = ["hhi_ingresos"]

# Ordered feature vector for ML model (21-dim)
FEATURE_ORDER = [
    "solvencia", "tier1_ratio", "leverage", "cobertura_provisiones",
    "patrimonio_activos", "morosidad", "pct_cartera_a", "concentracion_top10",
    "hhi_sectorial", "castigos_pct", "exposicion_re", "migracion",
    "composite_calidad", "roa", "roe", "margen_financiero", "cost_to_income",
    "liquidez_inmediata", "ltd", "liquidez_ajustada", "hhi_ingresos",
]

# XGBoost hyperparameters
XGBOOST_PARAMS = {
    "objective": "multi:softprob",
    "num_class": 10,
    "max_depth": 6,
    "learning_rate": 0.05,
    "n_estimators": 200,
    "subsample": 0.8,
    "colsample_bytree": 0.8,
    "reg_alpha": 0.1,
    "reg_lambda": 1.0,
    "eval_metric": "mlogloss",
    "use_label_encoder": False,
    "random_state": 42,
}
