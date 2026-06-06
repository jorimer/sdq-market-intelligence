"""IRMP configuration — now sourced from house doctrine.

The canonical weights, variable mapping, risk-increasing flags and bands live in
``shared/doctrine/regulatory.yaml`` (the control document).  This module exposes
them as the names the rest of the module already imports, so nothing downstream
changes.  Edit the doctrine YAML to change the index, never this file.
"""
from shared.doctrine import load_doctrine

# Single source of truth: the regulatory/IRMP doctrine.
IRMP_CONFIG = load_doctrine("regulatory")

# Backward-compatible module-level symbols (API/tests import these directly).
DIMENSION_WEIGHTS = dict(IRMP_CONFIG.dimension_weights)
DIMENSION_VARIABLES = {k: list(v) for k, v in IRMP_CONFIG.dimension_variables.items()}
RISK_INCREASING_VARIABLES = set(IRMP_CONFIG.risk_increasing)
VARIABLE_ORDER = list(IRMP_CONFIG.variable_order)
