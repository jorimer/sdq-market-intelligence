"""Tests de las reglas PURAS del motor de alerta temprana de pensiones (sin DB)."""
from modules.pension_intel.early_warning import (
    evaluate,
    format_alerts_text,
    percentile,
    rule_costo,
    rule_real,
    rule_rentab,
    rule_riesgo,
    rule_solvency_drop,
)


def test_percentile():
    assert percentile([10, 20, 30, 40], 0.20) == 16.0
    assert percentile([], 0.5) is None


def test_rentab_rezagada_bajo_p20():
    assert rule_rentab(5.0, 6.0) is not None       # por debajo del p20
    assert rule_rentab(8.0, 6.0) is None


def test_real_negativo_es_alta():
    a = rule_real(-1.2)
    assert a is not None and a.severity == "alta"
    assert rule_real(2.0) is None


def test_riesgo_sobre_p80():
    assert rule_riesgo(2.5, 1.8) is not None
    assert rule_riesgo(1.0, 1.8) is None


def test_costo_sobre_p80():
    assert rule_costo(0.9, 0.7) is not None
    assert rule_costo(0.5, 0.7) is None


def test_caida_solvencia_umbral_relativo():
    assert rule_solvency_drop(0.08) is not None    # cayó 8% ≥ 5%
    assert rule_solvency_drop(0.02) is None


def test_evaluate_ordena_alta_primero():
    m = {"real": -0.5, "rentab": 5.0, "sigma": 2.5, "costo": 0.9, "solvency_drop": 0.08}
    peers = {"rentab_p20": 6.0, "riesgo_p80": 1.8, "costo_p80": 0.7}
    alerts = evaluate(m, peers)
    assert alerts[0].severity == "alta"            # retorno real neg / caída solvencia primero
    codes = {a.code for a in alerts}
    assert {"retorno_real_negativo", "caida_solvencia", "rentab_rezagada",
            "riesgo_elevado", "costo_elevado"} <= codes


def test_format_text_vacio_y_con_alertas():
    assert "Sin banderas" in format_alerts_text({"alerts": []})
    txt = format_alerts_text({"alerts": [
        {"label": "Retorno real negativo", "severity": "alta", "value": -1.2,
         "threshold": 0.0, "basis": "pierde poder adquisitivo", "metric": "rentabilidad real %"},
    ]})
    assert "**Retorno real negativo**" in txt and "-1.2" in txt
