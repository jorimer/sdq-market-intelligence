"""Tests for modules.banking_score.scoring.engine — 19 financial indicators.

Validates:
- Each indicator produces scores in [0, 100]
- Score functions respond correctly to extreme and normal inputs
- Sub-component aggregation works correctly
- Deterministic scoring produces valid overall score and tier
- Simulation (iSRM) recalculates correctly from modified scores
"""
import pytest

from modules.banking_score.scoring.engine import (
    BankingDataInput,
    calculate_all_indicators,
    calculate_sub_components,
    calculate_deterministic_score,
    run_scoring,
    simulate_from_scores,
    calc_solvencia,
    calc_tier1_ratio,
    calc_leverage,
    calc_cobertura_provisiones,
    calc_patrimonio_activos,
    calc_morosidad,
    calc_pct_cartera_a,
    calc_concentracion_top10,
    calc_hhi_sectorial,
    calc_castigos_pct,
    calc_exposicion_re,
    calc_migracion,
    calc_composite_calidad,
    calc_roa,
    calc_roe,
    calc_margen_financiero,
    calc_cost_to_income,
    calc_liquidez_inmediata,
    calc_ltd,
    calc_liquidez_ajustada,
    calc_hhi_ingresos,
)
from modules.banking_score.scoring.rating_scale import map_rating_tier


# ─── Fixtures ────────────────────────────────────────────────────


@pytest.fixture
def healthy_bank():
    """A well-capitalized, profitable bank with good asset quality."""
    return BankingDataInput(
        patrimonio_tecnico=15_000,
        apr=100_000,
        capital_primario=12_000,
        exposicion_total=150_000,
        capital_tier1=11_000,
        contingentes=5_000,
        riesgo_mercado=2_000,
        provisiones=3_000,
        cartera_vencida_90d=2_000,
        activos_totales=200_000,
        cartera_bruta=120_000,
        cartera_categoria_a=108_000,
        cartera_total=120_000,
        suma_top10=36_000,
        hhi_sectorial_raw=1_200,
        castigos=600,
        exposicion_re=48_000,
        cartera_a_prev=105_000,
        utilidad_neta=2_500,
        activos_promedio=195_000,
        patrimonio_promedio=14_500,
        ingresos_financieros=18_000,
        gastos_financieros=8_000,
        activos_productivos_avg=170_000,
        gastos_operacionales=5_000,
        ingresos_operacionales=12_000,
        caja_valores=15_000,
        pasivos_cp=60_000,
        cartera_neta=117_000,
        depositos_totales=150_000,
        activos_liquidos=40_000,
        pasivos_exigibles=55_000,
        hhi_ingresos_raw=2_500,
    )


@pytest.fixture
def weak_bank():
    """A poorly-capitalized bank with high NPLs and low profitability."""
    return BankingDataInput(
        patrimonio_tecnico=5_000,
        apr=100_000,
        capital_primario=3_000,
        exposicion_total=200_000,
        capital_tier1=2_500,
        contingentes=10_000,
        riesgo_mercado=5_000,
        provisiones=500,
        cartera_vencida_90d=8_000,
        activos_totales=250_000,
        cartera_bruta=150_000,
        cartera_categoria_a=90_000,
        cartera_total=150_000,
        suma_top10=75_000,
        hhi_sectorial_raw=3_000,
        castigos=6_000,
        exposicion_re=10_000,
        cartera_a_prev=100_000,
        utilidad_neta=200,
        activos_promedio=245_000,
        patrimonio_promedio=4_800,
        ingresos_financieros=12_000,
        gastos_financieros=10_000,
        activos_productivos_avg=180_000,
        gastos_operacionales=10_000,
        ingresos_operacionales=11_000,
        caja_valores=3_000,
        pasivos_cp=80_000,
        cartera_neta=142_000,
        depositos_totales=120_000,
        activos_liquidos=10_000,
        pasivos_exigibles=90_000,
        hhi_ingresos_raw=5_500,
    )


@pytest.fixture
def zero_bank():
    """A bank with all-zero data (tests division by zero safety)."""
    return BankingDataInput()


# ─── SOLIDEZ FINANCIERA ──────────────────────────────────────────


class TestSolvencia:
    def test_healthy_bank(self, healthy_bank):
        r = calc_solvencia(healthy_bank)
        assert 0 <= r["score"] <= 100
        # 15000 / (100000+5000+2000) = 14.02% → (14.02/15)*100 ≈ 93.4
        assert r["raw"] == pytest.approx(14.0187, abs=0.01)

    def test_zero_denominator(self, zero_bank):
        r = calc_solvencia(zero_bank)
        assert r["raw"] == 0.0
        assert r["score"] == 0.0


class TestTier1Ratio:
    def test_healthy_bank(self, healthy_bank):
        r = calc_tier1_ratio(healthy_bank)
        assert 0 <= r["score"] <= 100
        # 12000/100000 = 12% → ((12-4.5)/4)*100 = 187.5 → clamped to 100
        assert r["score"] == 100.0

    def test_below_minimum(self):
        d = BankingDataInput(capital_primario=4_000, apr=100_000)
        r = calc_tier1_ratio(d)
        # 4% < 4.5% → score = 0
        assert r["score"] == 0.0


class TestLeverage:
    def test_healthy_bank(self, healthy_bank):
        r = calc_leverage(healthy_bank)
        assert 0 <= r["score"] <= 100
        # 11000/150000 = 7.33% → (7.33/6)*100 ≈ 122 → clamped 100
        assert r["score"] == 100.0


class TestCoberturaProvisiones:
    def test_healthy_bank(self, healthy_bank):
        r = calc_cobertura_provisiones(healthy_bank)
        assert 0 <= r["score"] <= 100
        # 3000/2000 = 150% → min(100, 150) = 100
        assert r["score"] == 100.0

    def test_low_coverage(self):
        d = BankingDataInput(provisiones=500, cartera_vencida_90d=2_000)
        r = calc_cobertura_provisiones(d)
        # 500/2000 = 25%
        assert r["score"] == pytest.approx(25.0, abs=0.1)


class TestPatrimonioActivos:
    def test_healthy_bank(self, healthy_bank):
        r = calc_patrimonio_activos(healthy_bank)
        assert 0 <= r["score"] <= 100
        # 15000/200000 = 7.5% → (7.5/12)*100 = 62.5
        assert r["score"] == pytest.approx(62.5, abs=0.1)


# ─── CALIDAD DE ACTIVOS ──────────────────────────────────────────


class TestMorosidad:
    def test_healthy_bank(self, healthy_bank):
        r = calc_morosidad(healthy_bank)
        assert 0 <= r["score"] <= 100
        # 2000/120000 = 1.67% → 100 - 1.67*10 = 83.3
        assert r["score"] == pytest.approx(83.33, abs=0.1)

    def test_high_npl(self):
        d = BankingDataInput(cartera_vencida_90d=15_000, cartera_bruta=100_000)
        r = calc_morosidad(d)
        # 15% → 100 - 15*10 = -50 → clamped to 0
        assert r["score"] == 0.0


class TestPctCarteraA:
    def test_healthy_bank(self, healthy_bank):
        r = calc_pct_cartera_a(healthy_bank)
        assert 0 <= r["score"] <= 100
        # 108000/120000 = 90% → (90/90)*100 = 100
        assert r["score"] == 100.0


class TestConcentracionTop10:
    def test_healthy_bank(self, healthy_bank):
        r = calc_concentracion_top10(healthy_bank)
        assert 0 <= r["score"] <= 100
        # 36000/120000 = 30% → 100 - (30-30)*1.5 = 100
        assert r["score"] == 100.0

    def test_high_concentration(self):
        d = BankingDataInput(suma_top10=80_000, cartera_bruta=100_000)
        r = calc_concentracion_top10(d)
        # 80% → 100 - (80-30)*1.5 = 100 - 75 = 25
        assert r["score"] == pytest.approx(25.0, abs=0.1)


class TestHhiSectorial:
    def test_low_hhi(self):
        d = BankingDataInput(hhi_sectorial_raw=1_000)
        r = calc_hhi_sectorial(d)
        assert r["score"] == 100.0

    def test_mid_hhi(self):
        d = BankingDataInput(hhi_sectorial_raw=2_000)
        r = calc_hhi_sectorial(d)
        # 100 - (2000-1500)/10 = 50
        assert r["score"] == pytest.approx(50.0, abs=0.1)

    def test_high_hhi(self):
        d = BankingDataInput(hhi_sectorial_raw=3_000)
        r = calc_hhi_sectorial(d)
        assert r["score"] == 0.0


class TestCastigosPct:
    def test_healthy_bank(self, healthy_bank):
        r = calc_castigos_pct(healthy_bank)
        assert 0 <= r["score"] <= 100
        # 600/120000 = 0.5% → 100 - 0.5*5 = 97.5
        assert r["score"] == pytest.approx(97.5, abs=0.1)


class TestExposicionRe:
    def test_optimal_at_40(self):
        d = BankingDataInput(exposicion_re=40_000, cartera_bruta=100_000)
        r = calc_exposicion_re(d)
        # 40% → 100 - |40-40|/1.5 = 100
        assert r["score"] == 100.0

    def test_deviation_from_40(self):
        d = BankingDataInput(exposicion_re=10_000, cartera_bruta=100_000)
        r = calc_exposicion_re(d)
        # 10% → 100 - |10-40|/1.5 = 100 - 20 = 80
        assert r["score"] == pytest.approx(80.0, abs=0.1)


class TestMigracion:
    def test_positive_growth(self, healthy_bank):
        r = calc_migracion(healthy_bank)
        assert 0 <= r["score"] <= 100
        # (108000-105000)/105000 = 2.86% → 100 - min(100, |2.86|*5) = 100 - 14.3 = 85.7
        assert r["score"] == pytest.approx(85.71, abs=0.1)

    def test_no_previous_data(self):
        d = BankingDataInput(cartera_categoria_a=100_000, cartera_a_prev=0)
        r = calc_migracion(d)
        assert r["raw"] == 0.0
        assert r["score"] == 100.0


class TestCompositeCalidad:
    def test_average_of_components(self, healthy_bank):
        indicators = calculate_all_indicators(healthy_bank)
        r = indicators["composite_calidad"]
        calidad_keys = [
            "morosidad", "pct_cartera_a", "concentracion_top10",
            "hhi_sectorial", "castigos_pct", "exposicion_re", "migracion",
        ]
        expected_avg = sum(indicators[k]["score"] for k in calidad_keys) / 7
        assert r["score"] == pytest.approx(expected_avg, abs=0.01)


# ─── EFICIENCIA Y RENTABILIDAD ───────────────────────────────────


class TestRoa:
    def test_healthy_bank(self, healthy_bank):
        r = calc_roa(healthy_bank)
        assert 0 <= r["score"] <= 100
        # 2500/195000 = 1.28% → (1.28/1.5)*100 = 85.5
        assert r["score"] == pytest.approx(85.47, abs=0.1)


class TestRoe:
    def test_healthy_bank(self, healthy_bank):
        r = calc_roe(healthy_bank)
        assert 0 <= r["score"] <= 100
        # 2500/14500 = 17.24% → (17.24/15)*100 = 114.9 → clamped 100
        assert r["score"] == 100.0


class TestMargenFinanciero:
    def test_healthy_bank(self, healthy_bank):
        r = calc_margen_financiero(healthy_bank)
        assert 0 <= r["score"] <= 100
        # (18000-8000)/170000 = 5.88% → (5.88/6)*100 = 98.0
        assert r["score"] == pytest.approx(98.04, abs=0.1)


class TestCostToIncome:
    def test_healthy_bank(self, healthy_bank):
        r = calc_cost_to_income(healthy_bank)
        assert 0 <= r["score"] <= 100
        # 5000/12000 = 41.67% → 100 - 41.67 = 58.33
        assert r["score"] == pytest.approx(58.33, abs=0.1)

    def test_very_efficient(self):
        d = BankingDataInput(gastos_operacionales=2_000, ingresos_operacionales=10_000)
        r = calc_cost_to_income(d)
        # 20% → 100 - 20 = 80
        assert r["score"] == pytest.approx(80.0, abs=0.1)


# ─── LIQUIDEZ ────────────────────────────────────────────────────


class TestLiquidezInmediata:
    def test_healthy_bank(self, healthy_bank):
        r = calc_liquidez_inmediata(healthy_bank)
        assert 0 <= r["score"] <= 100
        # 15000/60000 = 25% → (25/30)*100 = 83.3
        assert r["score"] == pytest.approx(83.33, abs=0.1)


class TestLtd:
    def test_optimal_at_80(self):
        d = BankingDataInput(cartera_neta=80_000, depositos_totales=100_000)
        r = calc_ltd(d)
        # 80% → 100 - 2*(80-80)^2/15^2 = 100
        assert r["score"] == 100.0

    def test_deviation_from_optimal(self, healthy_bank):
        r = calc_ltd(healthy_bank)
        assert 0 <= r["score"] <= 100
        # 117000/150000 = 78% → 100 - 2*(78-80)^2/225 = 100 - 0.036 ≈ 99.96
        assert r["score"] == pytest.approx(99.96, abs=0.1)


class TestLiquidezAjustada:
    def test_healthy_bank(self, healthy_bank):
        r = calc_liquidez_ajustada(healthy_bank)
        assert 0 <= r["score"] <= 100
        # 40000/55000 = 72.7% → (72.7/80)*100 = 90.9
        assert r["score"] == pytest.approx(90.91, abs=0.1)


# ─── DIVERSIFICACIÓN ─────────────────────────────────────────────


class TestHhiIngresos:
    def test_well_diversified(self):
        d = BankingDataInput(hhi_ingresos_raw=2_000)
        r = calc_hhi_ingresos(d)
        assert r["score"] == 100.0

    def test_moderately_concentrated(self):
        d = BankingDataInput(hhi_ingresos_raw=4_000)
        r = calc_hhi_ingresos(d)
        # 100 - (4000-3000)/20 = 50
        assert r["score"] == pytest.approx(50.0, abs=0.1)

    def test_highly_concentrated(self):
        d = BankingDataInput(hhi_ingresos_raw=6_000)
        r = calc_hhi_ingresos(d)
        assert r["score"] == 0.0


# ─── AGGREGATION & PIPELINE ─────────────────────────────────────


class TestCalculateAllIndicators:
    def test_returns_all_20_indicators(self, healthy_bank):
        indicators = calculate_all_indicators(healthy_bank)
        expected_keys = {
            "solvencia", "tier1_ratio", "leverage",
            "cobertura_provisiones", "patrimonio_activos",
            "morosidad", "pct_cartera_a", "concentracion_top10",
            "hhi_sectorial", "castigos_pct", "exposicion_re",
            "migracion", "composite_calidad",
            "roa", "roe", "margen_financiero", "cost_to_income",
            "liquidez_inmediata", "ltd", "liquidez_ajustada",
            "hhi_ingresos",
        }
        assert set(indicators.keys()) == expected_keys

    def test_all_scores_in_range(self, healthy_bank):
        indicators = calculate_all_indicators(healthy_bank)
        for name, vals in indicators.items():
            assert 0 <= vals["score"] <= 100, f"{name} score out of range: {vals['score']}"

    def test_zero_data_all_scores_in_range(self, zero_bank):
        indicators = calculate_all_indicators(zero_bank)
        for name, vals in indicators.items():
            assert 0 <= vals["score"] <= 100, f"{name} score out of range with zero data: {vals['score']}"


class TestSubComponents:
    def test_returns_5_components(self, healthy_bank):
        indicators = calculate_all_indicators(healthy_bank)
        subs = calculate_sub_components(indicators)
        expected_keys = {"solidez", "calidad", "eficiencia", "liquidez", "diversificacion"}
        assert set(subs.keys()) == expected_keys

    def test_all_scores_in_range(self, healthy_bank):
        indicators = calculate_all_indicators(healthy_bank)
        subs = calculate_sub_components(indicators)
        for comp, score in subs.items():
            assert 0 <= score <= 100, f"{comp} sub-component out of range: {score}"


class TestDeterministicScore:
    def test_returns_valid_range(self, healthy_bank):
        indicators = calculate_all_indicators(healthy_bank)
        subs = calculate_sub_components(indicators)
        score = calculate_deterministic_score(subs)
        assert 0 <= score <= 100

    def test_perfect_scores_give_100(self):
        subs = {"solidez": 100, "calidad": 100, "eficiencia": 100,
                "liquidez": 100, "diversificacion": 100}
        assert calculate_deterministic_score(subs) == 100.0

    def test_zero_scores_give_0(self):
        subs = {"solidez": 0, "calidad": 0, "eficiencia": 0,
                "liquidez": 0, "diversificacion": 0}
        assert calculate_deterministic_score(subs) == 0.0

    def test_weights_sum_to_1(self):
        from modules.banking_score.scoring.weights import SUB_COMPONENT_WEIGHTS
        assert sum(SUB_COMPONENT_WEIGHTS.values()) == pytest.approx(1.0)


class TestRunScoring:
    def test_full_pipeline_healthy_bank(self, healthy_bank):
        result = run_scoring(healthy_bank)
        assert "overall_score" in result
        assert "rating_tier" in result
        assert "tier_color" in result
        assert "sub_components" in result
        assert "indicators" in result
        assert "model_type" in result
        assert result["model_type"] == "deterministic"
        assert 0 <= result["overall_score"] <= 100
        assert result["rating_tier"].startswith("SDQ-")

    def test_full_pipeline_weak_bank(self, weak_bank):
        result = run_scoring(weak_bank)
        assert 0 <= result["overall_score"] <= 100
        # Weak bank should score lower than healthy
        healthy_result = run_scoring(BankingDataInput(
            patrimonio_tecnico=15_000, apr=100_000, capital_primario=12_000,
            exposicion_total=150_000, capital_tier1=11_000, contingentes=5_000,
            riesgo_mercado=2_000, provisiones=3_000, cartera_vencida_90d=2_000,
            activos_totales=200_000, cartera_bruta=120_000,
            cartera_categoria_a=108_000, cartera_total=120_000,
            suma_top10=36_000, hhi_sectorial_raw=1_200, castigos=600,
            exposicion_re=48_000, cartera_a_prev=105_000, utilidad_neta=2_500,
            activos_promedio=195_000, patrimonio_promedio=14_500,
            ingresos_financieros=18_000, gastos_financieros=8_000,
            activos_productivos_avg=170_000, gastos_operacionales=5_000,
            ingresos_operacionales=12_000, caja_valores=15_000,
            pasivos_cp=60_000, cartera_neta=117_000, depositos_totales=150_000,
            activos_liquidos=40_000, pasivos_exigibles=55_000,
            hhi_ingresos_raw=2_500,
        ))
        assert result["overall_score"] < healthy_result["overall_score"]

    def test_zero_data_does_not_crash(self, zero_bank):
        result = run_scoring(zero_bank)
        assert 0 <= result["overall_score"] <= 100


class TestSimulateFromScores:
    def test_perfect_scores(self):
        scores = {
            "solvencia": 100, "tier1_ratio": 100, "leverage": 100,
            "cobertura_provisiones": 100, "patrimonio_activos": 100,
            "morosidad": 100, "pct_cartera_a": 100, "concentracion_top10": 100,
            "hhi_sectorial": 100, "castigos_pct": 100, "exposicion_re": 100,
            "migracion": 100,
            "roa": 100, "roe": 100, "margen_financiero": 100, "cost_to_income": 100,
            "liquidez_inmediata": 100, "ltd": 100, "liquidez_ajustada": 100,
            "hhi_ingresos": 100,
        }
        result = simulate_from_scores(scores)
        assert result["overall_score"] == 100.0
        assert result["rating_tier"] == "SDQ-AAA"

    def test_zero_scores(self):
        scores = {
            "solvencia": 0, "tier1_ratio": 0, "leverage": 0,
            "cobertura_provisiones": 0, "patrimonio_activos": 0,
            "morosidad": 0, "pct_cartera_a": 0, "concentracion_top10": 0,
            "hhi_sectorial": 0, "castigos_pct": 0, "exposicion_re": 0,
            "migracion": 0,
            "roa": 0, "roe": 0, "margen_financiero": 0, "cost_to_income": 0,
            "liquidez_inmediata": 0, "ltd": 0, "liquidez_ajustada": 0,
            "hhi_ingresos": 0,
        }
        result = simulate_from_scores(scores)
        assert result["overall_score"] == 0.0
        assert result["rating_tier"] == "SDQ-D"

    def test_recalculates_composite_calidad(self):
        scores = {
            "morosidad": 80, "pct_cartera_a": 90, "concentracion_top10": 70,
            "hhi_sectorial": 60, "castigos_pct": 85, "exposicion_re": 75,
            "migracion": 95,
        }
        result = simulate_from_scores(scores)
        # composite_calidad should be recalculated as average
        expected_composite = (80 + 90 + 70 + 60 + 85 + 75 + 95) / 7
        assert scores["composite_calidad"] == pytest.approx(expected_composite, abs=0.01)
