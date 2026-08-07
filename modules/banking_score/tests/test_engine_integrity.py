"""Data-integrity tests for the credit-scoring engine.

Missing inputs must NOT score as perfect/zero — the indicator is marked
unavailable, excluded from its sub-component, and the overall score renormalizes
over what was actually measured.
"""
from types import SimpleNamespace

from modules.banking_score.scoring.engine import (
    calculate_all_indicators,
    calculate_deterministic_score,
    calculate_sub_components,
    run_scoring,
)


def _data(**kw):
    """A data object where every field defaults to None (missing)."""
    fields = [
        "patrimonio_tecnico", "apr", "capital_primario", "exposicion_total",
        "capital_tier1", "contingentes", "riesgo_mercado", "provisiones",
        "cartera_vencida_90d", "activos_totales", "cartera_bruta",
        "cartera_categoria_a", "cartera_total", "suma_top10", "hhi_sectorial_raw",
        "castigos", "exposicion_re", "cartera_a_prev", "utilidad_neta",
        "activos_promedio", "patrimonio_promedio", "ingresos_financieros",
        "gastos_financieros", "activos_productivos_avg", "gastos_operacionales",
        "ingresos_operacionales", "caja_valores", "pasivos_cp", "cartera_neta",
        "depositos_totales", "activos_liquidos", "pasivos_exigibles",
        "hhi_ingresos_raw",
    ]
    ns = {f: None for f in fields}
    ns.update(kw)
    return SimpleNamespace(**ns)


def test_missing_inputs_are_not_scored_as_perfect():
    # No NPL data → morosidad must be N/D, not a false 100.
    ind = calculate_all_indicators(_data(cartera_bruta=1000))  # vencida is None
    assert ind["morosidad"]["available"] is False
    # Indicators with no source at all → unavailable.
    for k in ("concentracion_top10", "hhi_sectorial", "exposicion_re", "hhi_ingresos"):
        assert ind[k]["available"] is False


def test_subcomponent_is_nd_when_no_indicator_available():
    subs = calculate_sub_components(calculate_all_indicators(_data()))
    # Nothing populated → every sub-component is N/D (None), never a fabricated number.
    assert all(v is None for v in subs.values())


def test_overall_renormalizes_over_available_subcomponents():
    # Only solidez + liquidez measurable; calidad/eficiencia/div are N/D.
    d = _data(
        patrimonio_tecnico=120, apr=1000, activos_totales=1500,  # solidez
        activos_liquidos=400, pasivos_exigibles=500,             # liquidez (ajustada)
        caja_valores=100, pasivos_cp=400, cartera_neta=800, depositos_totales=1000,
    )
    res = run_scoring(d, entity_type="banca_multiple")
    subs = res["sub_components"]
    assert subs["calidad"] is None and subs["diversificacion"] is None
    assert subs["solidez"] is not None and subs["liquidez"] is not None
    # Overall is a weighted average of ONLY the present sub-components (renormalized).
    present = {k: v for k, v in subs.items() if v is not None}
    wp = res["weight_profile"]
    tw = sum(wp[k] for k in present)
    expected = round(sum(present[k] * wp[k] for k in present) / tw, 2)
    assert abs(res["overall_score"] - expected) < 0.05
    assert res["model_version"] == "1.2"


def test_fully_populated_data_still_scores_all_subcomponents():
    # Backward-compat: when everything is present, no sub-component is N/D.
    full = _data(**{f: 1.0 for f in [
        "patrimonio_tecnico", "apr", "capital_primario", "exposicion_total",
        "capital_tier1", "provisiones", "cartera_vencida_90d", "activos_totales",
        "cartera_bruta", "cartera_categoria_a", "cartera_total", "suma_top10",
        "hhi_sectorial_raw", "castigos", "exposicion_re", "cartera_a_prev",
        "utilidad_neta", "activos_promedio", "patrimonio_promedio",
        "ingresos_financieros", "gastos_financieros", "activos_productivos_avg",
        "gastos_operacionales", "ingresos_operacionales", "caja_valores",
        "pasivos_cp", "cartera_neta", "depositos_totales", "activos_liquidos",
        "pasivos_exigibles", "hhi_ingresos_raw",
    ]})
    subs = calculate_sub_components(calculate_all_indicators(full))
    assert all(v is not None for v in subs.values())
