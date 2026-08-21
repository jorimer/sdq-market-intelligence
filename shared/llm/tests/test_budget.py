"""Tests del presupuesto diario LLM: contabilidad, techo y corte suave."""
import pytest

from shared.llm import budget


@pytest.fixture(autouse=True)
def _reset_state(monkeypatch):
    monkeypatch.setattr(budget, "_mem_day", "")
    monkeypatch.setattr(budget, "_mem_spent", 0.0)
    monkeypatch.setattr(budget, "_last_over_budget_log", 0.0)
    monkeypatch.setattr(budget.settings, "REDIS_URL", "")
    budget.invalidate_limit_cache()  # el techo se memoriza: sin esto un test pisa al otro
    # Estos tests miden el CONTADOR, no la configuración: sin cortar la lectura a la base,
    # el resultado dependería de si el entorno donde corren tiene (o no) una fila guardada.
    # Sin base, `current_limit` cae al valor de entorno, que es el que cada test fija.
    monkeypatch.setattr("shared.database.session.SessionLocal", _sin_base)
    yield
    budget.invalidate_limit_cache()


def _sin_base():
    raise RuntimeError("sin base en este test")


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


def test_el_DEFAULT_del_techo_no_es_cero():
    """Un entorno que nunca definió ``LLM_DAILY_BUDGET_USD`` NO queda sin techo.

    El 2026-08-20 una tarea de pre-calentado generó informes que nadie pidió y gastó USD 127
    en un día: el techo estaba en su default 0 —sin techo— así que no había nada que pudiera
    cortarla. "Sin techo" no puede ser el estado en que se cae por omisión; apagarlo (=0) es
    una decisión que se toma explícitamente por variable de entorno, no un olvido.

    Este test NO fija el número (cada despliegue calibra el suyo mirando su propio gasto en
    ``GET /api/v1/operations/llm-spend``): fija que exista.
    """
    from shared.config.settings import Settings

    assert Settings.model_fields["LLM_DAILY_BUDGET_USD"].default > 0, (
        "el default del presupuesto diario volvió a 0: cualquier entorno que no defina la "
        "variable queda otra vez sin techo, que es como se fueron USD 127 en un día.")


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


# ── El techo vigente: Configuración manda, el entorno respalda ────────────────
# El 2026-08-20 el gasto se fue de USD 127 en un día y bajar el techo requería un redeploy.
# Ahora el admin lo mueve en caliente desde Configuración; estas pruebas fijan la precedencia
# y, sobre todo, qué pasa cuando la lectura falla.

def _techo_de_configuracion(monkeypatch, valor):
    """Sustituye el resolutor que ``current_limit`` importa perezosamente."""
    import shared.settings.service as svc
    monkeypatch.setattr(svc, "get_llm_daily_budget", lambda db: valor, raising=False)
    monkeypatch.setattr("shared.database.session.SessionLocal",
                        lambda: type("S", (), {"close": lambda self: None})())


def test_el_techo_de_configuracion_manda_sobre_el_del_entorno(monkeypatch):
    monkeypatch.setattr(budget.settings, "LLM_DAILY_BUDGET_USD", 25.0, raising=False)
    _techo_de_configuracion(monkeypatch, 5.0)
    assert budget.current_limit() == 5.0
    budget.record_usage("claude-sonnet-4-6", 1_000_000, 200_000)  # $6 > $5
    assert budget.budget_allows() is False, "el techo de Configuración no cortó"


def test_si_no_se_puede_leer_la_configuracion_manda_el_entorno_y_NUNCA_cero(monkeypatch):
    """Quedarse sin techo porque falló una consulta es el peor momento para no tenerlo:
    un corte de base durante una fuga de gasto dejaría correr la fuga."""
    monkeypatch.setattr(budget.settings, "LLM_DAILY_BUDGET_USD", 25.0, raising=False)

    def _explota():
        raise RuntimeError("base caída")
    monkeypatch.setattr("shared.database.session.SessionLocal", _explota)
    assert budget.current_limit() == 25.0


def test_el_techo_se_memoriza_y_la_invalidacion_lo_relee(monkeypatch):
    """Se lee antes de CADA llamada al modelo: sin memo, cada generación abriría una
    conexión para releer un número que cambia una vez al mes."""
    lecturas = []

    import shared.settings.service as svc

    def _contar(db):
        lecturas.append(1)
        return 7.0
    monkeypatch.setattr(svc, "get_llm_daily_budget", _contar, raising=False)
    monkeypatch.setattr("shared.database.session.SessionLocal",
                        lambda: type("S", (), {"close": lambda self: None})())

    assert budget.current_limit() == 7.0
    assert budget.current_limit() == 7.0
    assert len(lecturas) == 1, "el techo se releyó de la base en cada llamada"

    budget.invalidate_limit_cache()
    assert budget.current_limit() == 7.0
    assert len(lecturas) == 2, "invalidar no forzó la relectura"
