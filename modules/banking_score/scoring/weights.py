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
