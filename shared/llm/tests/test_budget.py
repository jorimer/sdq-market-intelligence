"""Tests del presupuesto diario LLM: contabilidad, techo y corte suave."""
import pytest

from shared.llm import budget


@pytest.fixture(autouse=True)
def _reset_state(monkeypatch):
    monkeypatch.setattr(budget, "_mem_day", "")
    monkeypatch.setattr(budget, "_mem_spent", 0.0)
    monkeypatch.setattr(budget, "_last_over_budget_log", 0.0)
    monkeypatch.setattr(budget.settings, "REDIS_URL", "")
    yield


def test_estimate_cost_por_modelo():
    # Sonnet 4.6: $3/$15 por MTok
    assert budget.estimate_cost("claude-sonnet-4-6", 1_000_000, 1_000_000) == 18.0
    # Haiku 4.5: $1/$5 por MTok
    assert budget.estimate_cost("claude-haiku-4-5", 1_000_000, 1_000_000) == 6.0
    # modelo desconocido → tarifa Sonnet (conservador)
    assert budget.estimate_cost("claude-x", 1_000_000, 0) == 3.0


def test_record_usage_acumula_en_memoria_sin_redis():
    c1 = budget.record_usage("claude-sonnet-4-6", 100_000, 10_000)
    c2 = budget.record_usage("claude-sonnet-4-6", 100_000, 10_000)
    assert c1 == c2 == pytest.approx(0.45)
    assert budget.spent_today() == pytest.approx(0.9)


def test_sin_techo_configurado_siempre_permite(monkeypatch):
    monkeypatch.setattr(budget.settings, "LLM_DAILY_BUDGET_USD", 0.0, raising=False)
    budget.record_usage("claude-sonnet-4-6", 10_000_000, 10_000_000)  # $180
    assert budget.budget_allows() is True


def test_corte_suave_al_superar_techo(monkeypatch):
    monkeypatch.setattr(budget.settings, "LLM_DAILY_BUDGET_USD", 1.0, raising=False)
    assert budget.budget_allows() is True
    budget.record_usage("claude-sonnet-4-6", 200_000, 40_000)  # $1.20 > $1.00
    assert budget.budget_allows() is False


def test_spent_today_lee_redis_si_hay(monkeypatch):
    monkeypatch.setattr(budget, "cache_get", lambda k: "3.25")
    assert budget.spent_today() == 3.25


def test_contador_resetea_al_cambiar_de_dia(monkeypatch):
    budget.record_usage("claude-sonnet-4-6", 100_000, 0)
    assert budget.spent_today() > 0
    monkeypatch.setattr(budget, "_today", lambda: "2099-01-01")
    assert budget.spent_today() == 0.0
