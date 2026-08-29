"""Tests de la tabla de sensibilidades (Fase 4).

Incluye el test ROUND-TRIP que fija los inversos de ``sensitivity._CURVES`` a las curvas
forward reales de ``engine.py``: si una curva se recalibra sin actualizar su inverso, el
test falla ruidoso (no se publica un umbral crudo equivocado).
"""
import pytest

from modules.banking_score.models.models import BankingData
from modules.banking_score.scoring import engine
from modules.banking_score.scoring import hhi_estratos
from modules.banking_score.scoring.sensitivity import _CURVES, sensitivity_table


# key → (constructor de BankingData que fija un raw dado, función calc del engine).
def _bd(**kw):
    return BankingData(**kw)


_ENGINE_CASES = {
    # Fast-path por campo pct (el raw entra directo).
    "solvencia": (lambda raw: _bd(solvencia_pct=raw), engine.calc_solvencia),
    "tier1_ratio": (lambda raw: _bd(tier1_pct=raw), engine.calc_tier1_ratio),
    "cobertura_provisiones": (lambda raw: _bd(cobertura_pct=raw), engine.calc_cobertura_provisiones),
    "morosidad": (lambda raw: _bd(morosidad_pct=raw), engine.calc_morosidad),
    "pct_cartera_a": (lambda raw: _bd(cartera_vigente_pct=raw), engine.calc_pct_cartera_a),
    "castigos_pct": (lambda raw: _bd(castigos_pct=raw), engine.calc_castigos_pct),
    "exposicion_re": (lambda raw: _bd(exposicion_re_pct=raw), engine.calc_exposicion_re),
    # Ratios de dos campos (denominador = 100 → raw = numerador).
    "leverage": (lambda raw: _bd(capital_tier1=raw, exposicion_total=100), engine.calc_leverage),
    "patrimonio_activos": (lambda raw: _bd(patrimonio_tecnico=raw, activos_totales=100), engine.calc_patrimonio_activos),
    "concentracion_top10": (lambda raw: _bd(suma_top10=raw, cartera_total=100), engine.calc_concentracion_top10),
    "cost_to_income": (lambda raw: _bd(gastos_operacionales=raw, ingresos_operacionales=100), engine.calc_cost_to_income),
    "liquidez_inmediata": (lambda raw: _bd(caja_valores=raw, pasivos_cp=100), engine.calc_liquidez_inmediata),
    "liquidez_ajustada": (lambda raw: _bd(activos_liquidos=raw, pasivos_exigibles=100), engine.calc_liquidez_ajustada),
    "ltd": (lambda raw: _bd(cartera_neta=raw, depositos_totales=100), engine.calc_ltd),
    # Índices HHI (raw directo).
    "hhi_sectorial": (lambda raw: _bd(hhi_sectorial_raw=raw), engine.calc_hhi_sectorial),
    "hhi_ingresos": (lambda raw: _bd(hhi_ingresos_raw=raw), engine.calc_hhi_ingresos),
}

# raws de prueba por indicador que caen en la parte NO saturada de la curva (score∈(0,100)),
# donde el inverso es válido.
_TEST_RAW = {
    "solvencia": 12.0, "tier1_ratio": 6.5, "cobertura_provisiones": 70.0,
    # Valores dentro del rango útil de cada curva recalibrada (2026-08-08): un raw que
    # satura no puede validar el inverso, porque la curva forward pierde información.
    "morosidad": 3.0, "pct_cartera_a": 96.0, "castigos_pct": 1.5,
    "exposicion_re": 55.0, "leverage": 4.0, "patrimonio_activos": 9.0,
    "concentracion_top10": 45.0, "cost_to_income": 62.0, "liquidez_inmediata": 20.0,
    "liquidez_ajustada": 60.0, "ltd": 95.0, "hhi_sectorial": 2000.0, "hhi_ingresos": 6000.0,
}


@pytest.mark.parametrize("key", sorted(_ENGINE_CASES))
def test_inverse_curve_matches_engine_roundtrip(key):
    """to_raw(calc(raw).score) ≈ raw — el inverso invierte la curva forward del engine."""
    make, calc = _ENGINE_CASES[key]
    raw = _TEST_RAW[key]
    score = calc(make(raw))["score"]
    assert 0.0 < score < 100.0, f"{key}: raw de prueba saturó la curva (score={score})"
    recovered = _CURVES[key].to_raw(score, raw)
    # La tolerancia NO puede ser una constante para los 16: el motor redondea el score a dos
    # decimales, y cuánto raw vale una centésima depende de la PENDIENTE de cada curva. En
    # morosidad son milésimas de punto; en el HHI sectorial, cuyo rango crudo son miles de
    # unidades, media unidad. Se deriva de la curva misma en vez de fijarse a ojo.
    por_punto = abs(_CURVES[key].to_raw(score + 1.0, raw) - recovered)
    assert recovered == pytest.approx(raw, abs=max(0.01, 0.02 * por_punto)), \
        f"{key}: {recovered} != {raw} (score={score})"


def test_every_engine_case_has_a_curve():
    # Todo indicador con curva forward testeada tiene su inverso registrado.
    assert set(_ENGINE_CASES).issubset(set(_CURVES))


def test_sensitivity_symmetric_and_signed():
    inds = {
        "solvencia": {"raw": 16.8, "score": 100.0, "available": True},
        "morosidad": {"raw": 3.2, "score": 68.0, "available": True},
        "roe": {"raw": 9.0, "score": 60.0, "available": True},
        "cost_to_income": {"raw": 62.0, "score": 56.0, "available": True},
        "composite_calidad": {"raw": 68.0, "score": 68.0, "available": True},
    }
    r = sensitivity_table(inds, entity_type="banca_multiple", top=3)
    assert r["baseline_overall"] > 0
    # Palancas al alza suben el score; riesgos a la baja lo bajan.
    assert all(x["delta_overall"] > 0 for x in r["palancas_alza"])
    assert all(x["delta_overall"] < 0 for x in r["riesgos_baja"])
    # Umbral de alza mejora en la dirección correcta (solvencia N/A: ya fuerte; morosidad baja).
    mor_up = next((x for x in r["palancas_alza"] if x["indicador"] == "morosidad"), None)
    if mor_up:
        assert mor_up["umbral_raw"] < mor_up["raw_actual"]  # morosidad: menor es mejor
    # composite_calidad no es palanca (derivado).
    assert all(x["indicador"] != "composite_calidad"
               for x in r["palancas_alza"] + r["riesgos_baja"])


def test_sensitivity_downside_ranks_high_weight_first():
    # Solidez (peso 40%) es el único sub-componente presente aquí; su solvencia en el
    # borde de banda debe ser el mayor riesgo a la baja (mueve todo el peso).
    inds = {
        "solvencia": {"raw": 14.0, "score": 93.0, "available": True},
        "leverage": {"raw": 5.4, "score": 90.0, "available": True},
        "patrimonio_activos": {"raw": 11.0, "score": 91.0, "available": True},
        "roe": {"raw": 10.8, "score": 72.0, "available": True},
    }
    r = sensitivity_table(inds, entity_type="banca_multiple", top=4)
    assert r["riesgos_baja"], "debería haber riesgos a la baja"
    # El de mayor pérdida está en solidez (el sub-componente de mayor peso).
    assert r["riesgos_baja"][0]["sub"] == "solidez"


def test_sensitivity_empty_when_no_indicators():
    r = sensitivity_table({}, entity_type="banca_multiple")
    assert r["palancas_alza"] == [] and r["riesgos_baja"] == []


@pytest.mark.parametrize("estrato", sorted(hhi_estratos.ANCLAS))
def test_inverso_del_hhi_sectorial_round_trip_por_estrato(estrato):
    """El HHI sectorial se calibra por estrato: cada curva tiene que invertir la SUYA.

    Con una curva global bastaba el round-trip de arriba. Con cuatro estratos, que el
    universo invierta bien no dice nada de si la curva de las AAyP lo hace — y el inverso es
    el que alimenta el `nivel_de_referencia` que se publica en los informes.
    """
    p10, p90 = hhi_estratos.ANCLAS[estrato]
    raw = (p10 + p90) / 2.0
    score = engine.calc_hhi_sectorial(_bd(hhi_sectorial_raw=raw), estrato)["score"]
    assert 0.0 < score < 100.0
    recuperado = _CURVES["hhi_sectorial"].to_raw(score, raw, estrato)
    assert recuperado == pytest.approx(raw, abs=0.02 * (p90 - p10) / 100.0 * 100)


def test_el_inverso_del_hhi_distingue_estratos():
    """Si el inverso ignorara el estrato, los informes citarían el nivel de referencia de la
    curva equivocada — con HTTP 200 y sin que nada fallara."""
    niveles = {e: _CURVES["hhi_sectorial"].to_raw(50.0, 3000.0, e)
               for e in hhi_estratos.ANCLAS}
    assert len(set(niveles.values())) == len(niveles), f"estratos colapsados: {niveles}"
