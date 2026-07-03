"""Tests de las reglas PURAS del motor de alerta temprana (sin DB)."""
from modules.banking_score.early_warning import (
    evaluate,
    format_alerts_text,
    percentile,
    rule_concentration,
    rule_coverage,
    rule_funding,
    rule_growth,
    rule_liquidity,
    rule_morosidad,
    rule_solvency,
)


def test_percentile_interpola():
    assert percentile([10, 20, 30, 40], 0.90) == 37.0
    assert percentile([], 0.5) is None
    assert percentile([5], 0.9) == 5


def test_growth_solo_si_supera_pares_y_piso():
    assert rule_growth(0.40, 0.30) is not None            # > p90 y > 25%
    assert rule_growth(0.20, 0.10) is None                # no supera el piso 25%
    assert rule_growth(0.28, 0.35) is None                # no supera p90
    assert rule_growth(None, 0.3) is None


def test_funding_sobre_p90():
    assert rule_funding(8.0, 6.0) is not None
    assert rule_funding(5.0, 6.0) is None


def test_coverage_severidad():
    assert rule_coverage(120) is None
    assert rule_coverage(80).severity == "media"          # < 100
    assert rule_coverage(50).severity == "alta"           # < 60


def test_morosidad_dispara_por_multiplo_o_pp():
    assert rule_morosidad(6.0, 3.0) is not None            # 2× (≥1.5×)
    assert rule_morosidad(5.0, 3.0) is not None            # +2pp
    assert rule_morosidad(3.5, 3.0) is None                # ni ×1.5 ni +2pp


def test_solvency_cerca_del_piso():
    assert rule_solvency(15) is None
    assert rule_solvency(11.5).severity == "media"         # < 12
    assert rule_solvency(10.2).severity == "alta"          # < 10.5


def test_liquidity_por_fuga_o_piso():
    assert rule_liquidity(20.0, -0.15).severity == "alta"  # fuga de depósitos
    assert rule_liquidity(10.0, 0.0).severity == "media"   # bajo el piso de liquidez
    assert rule_liquidity(20.0, 0.0) is None


def test_concentration():
    assert rule_concentration(35) is not None
    assert rule_concentration(25) is None


def test_evaluate_ordena_alta_primero():
    m = {"solvencia_pct": 10.2, "cobertura_pct": 80, "concentration_pct": 40}
    peers = {"growth_p90": None, "funding_p90": None}
    alerts = evaluate(m, peers)
    codes = [a.code for a in alerts]
    assert "solvencia_piso" in codes and "brecha_provisiones" in codes and "concentracion" in codes
    assert alerts[0].severity == "alta"                    # la 'alta' va primero


def test_format_alerts_text_vacio_y_con_alertas():
    empty = format_alerts_text({"alerts": []})
    assert "Sin banderas" in empty and "no detecta fraude" in empty
    txt = format_alerts_text({"alerts": [
        {"label": "Salto de morosidad", "severity": "alta", "value": 4.83,
         "threshold": 3.0, "basis": "Deterioro diferido", "metric": "morosidad %"},
    ]})
    assert "**Salto de morosidad**" in txt and "4.83" in txt and "umbral 3.0" in txt
