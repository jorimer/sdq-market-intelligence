"""Configuración global de pytest (aplica a toda la suite: modules/ + shared/).

Hermeticidad frente al `.env` local: en dev el `.env` trae una ANTHROPIC_API_KEY REAL
(narrativa IA en local), pero la suite está escrita para el entorno de CI SIN key —
varios tests asertan la degradación a ``static_fallback`` (series macro con with_ai,
degradación del motor, forense histórico) y con key real llamarían al API de verdad:
resultado no determinista y gasto por corrida. El fixture autouse de abajo neutraliza
la key en CADA test, así local == CI y ningún test gasta llamadas reales. Un test que
necesite simular una key la setea explícitamente con monkeypatch DESPUÉS del autouse
(p. ej. shared/source_intel/tests), lo cual sigue funcionando.
"""
import pytest


@pytest.fixture(autouse=True)
def _sin_anthropic_key_real(monkeypatch):
    from shared.config.settings import settings
    from shared.narrative.claude_engine import narrative_engine

    monkeypatch.setattr(settings, "ANTHROPIC_API_KEY", "")
    # El motor singleton CACHEA el cliente (_get_client). Si un test previo instanció
    # uno (key simulada), vaciar la key no bastaría: se resetea también el cliente.
    monkeypatch.setattr(narrative_engine, "_client", None)
    # Red extra: si algún camino re-leyera el entorno (SDK, Settings() nueva).
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)


@pytest.fixture(autouse=True)
def _sin_cache_de_correo():
    """El emisor memoriza su configuración unos segundos (TTL) para no consultar la base en
    cada entrega de un barrido. Esa memoria es correcta en producción y venenosa entre
    tests: un test que configura SMTP le filtraría el canal al siguiente, que asserta que
    NO hay canal. Se vacía antes y después de cada uno."""
    from shared.notifications import email as mail

    mail.invalidar_cache()
    yield
    mail.invalidar_cache()
