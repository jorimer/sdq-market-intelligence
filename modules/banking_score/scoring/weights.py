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

#: FAMILIAS de Solidez: un HECHO, un voto.
#:
#: Los cinco indicadores de Solidez no son cinco hechos. `solvencia`, `tier1_ratio` y
#: `leverage` miden todos capital sobre ACTIVOS PONDERADOS POR RIESGO —cambian el numerador
#: (patrimonio técnico o capital primario) y poco más—, así que el promedio simple le daba a
#: ese único hecho el 60 % de la dimensión. Y cuando la entidad no tiene capital secundario,
#: dos de ellos son EXACTAMENTE el mismo número: 9 de 43 entidades al corte 2026-03.
#:
#: Con familias, la adecuación de capital pesa 1/3 igual que la cobertura de provisiones y
#: que el capital sobre activos SIN ponderar. Los tres indicadores siguen calculándose y
#: publicándose: lo que cambia es que no votan tres veces.
#:
#: Impacto MEDIDO sobre las 43 entidades calificadas al corte más reciente: Δ medio −1,95 en
#: el score de Solidez (máximo −8,74), que sobre el score global es del orden de −0,75. Ver
#: `docs/CHANGELOG_METODOLOGIA.md`.
#:
#: Un indicador que no esté en ninguna familia se trata como su propia familia — así, agregar
#: uno nuevo no lo deja fuera del promedio en silencio.
SOLIDEZ_FAMILIAS = (
    ("capital_ponderado", ("solvencia", "tier1_ratio", "leverage")),
    ("cobertura", ("cobertura_provisiones",)),
    ("capital_sobre_activos", ("patrimonio_activos",)),
)

# `composite_calidad` NO va acá: es la MEDIA de estos siete, y promediar la media de un
# conjunto junto al conjunto da exactamente la misma media —comprobado sobre las 43 entidades
# del panel: la diferencia máxima con `calidad_score` es 0,0043, puro redondeo—. O sea que no
# aportaba nada, pero dejaba puesta una trampa: el día que alguien pondere dentro de Calidad,
# como se hizo en Solidez, el compuesto adquiere peso real y ahí sí cada indicador cuenta dos
# veces. Se sigue calculando y publicando como resumen; lo que no hace es votar.
CALIDAD_INDICATORS = [
    "morosidad", "pct_cartera_a", "concentracion_top10",
    "hhi_sectorial", "castigos_pct", "exposicion_re",
    "migracion",
]

EFICIENCIA_INDICATORS = ["roa", "roe", "margen_financiero", "cost_to_income"]

LIQUIDEZ_INDICATORS = ["liquidez_inmediata", "ltd", "liquidez_ajustada"]

DIVERSIFICACION_INDICATORS = ["hhi_ingresos"]

def peso_efectivo_por_indicador(entity_type=None) -> dict:
    """Cuánto pesa CADA indicador en el score global, para un tipo de entidad.

    Se DERIVA de las mismas constantes que aplica el motor —los pesos de sub-componente,
    las listas por dimensión y las familias de Solidez— en vez de transcribirse. Una tabla
    de pesos escrita a mano se desincroniza el día que alguien recalibre, y lo que publica
    no es un número desactualizado cualquiera: es la cobertura del índice, o sea cuánto de
    lo que afirmamos se sostiene en dato real.

    Ojo con Solidez: NO es `0.40 / 5`. Sus cinco indicadores se promedian por FAMILIA (un
    hecho, un voto), así que `solvencia` pesa `0.40 · ⅓ · ⅓` y `patrimonio_activos`, que es
    familia de uno solo, pesa `0.40 · ⅓`.

    `composite_calidad` NO aparece: es la media de los siete de Calidad y no vota. Quien lo
    emita como señal debe darle peso 0, o el mismo hecho contaría dos veces.
    """
    pesos_dim = get_sub_component_weights(entity_type)
    fuera = {}

    # Solidez, por familias. Un indicador que no esté en ninguna es su propia familia, igual
    # que en el motor: así, agregar uno nuevo no lo deja fuera del promedio en silencio.
    en_familia = {i for _, miembros in SOLIDEZ_FAMILIAS for i in miembros}
    familias = list(SOLIDEZ_FAMILIAS) + [
        (i, (i,)) for i in SOLIDEZ_INDICATORS if i not in en_familia]
    if familias:
        peso_familia = pesos_dim.get("solidez", 0.0) / len(familias)
        for _, miembros in familias:
            if miembros:
                for indicador in miembros:
                    fuera[indicador] = peso_familia / len(miembros)

    # El resto: media simple de sus indicadores, como hace el motor.
    for dimension, indicadores in (("calidad", CALIDAD_INDICATORS),
                                   ("eficiencia", EFICIENCIA_INDICATORS),
                                   ("liquidez", LIQUIDEZ_INDICATORS),
                                   ("diversificacion", DIVERSIFICACION_INDICATORS)):
        if indicadores:
            peso = pesos_dim.get(dimension, 0.0) / len(indicadores)
            for indicador in indicadores:
                fuera[indicador] = peso
    return fuera


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
