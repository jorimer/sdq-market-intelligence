"""Tras un evento de datos, el suscriptor de products recalcula readiness y NADA MÁS.

En particular NO dispara ``prewarm-report-cache``. Antes sí lo hacía, y ese disparo era el
agujero: el pre-calentado se había apagado en la consola, pero la cascada por evento no mira
la agenda, así que el primer sync del día lo resucitaba y volvía a gastar IA. Apagar el
precalentado es también no dispararlo desde acá.
"""
import shared.operations.service as ops_service
from shared.products import events


class _DummyDB:
    def close(self):
        pass

    def rollback(self):
        pass


def _patch_common(monkeypatch, trigger_impl):
    monkeypatch.setattr(events, "SessionLocal", lambda: _DummyDB())
    monkeypatch.setattr(events, "recompute_readiness", lambda db: None)
    monkeypatch.setattr(ops_service, "trigger", trigger_impl)


def test_data_event_triggers_no_operation(monkeypatch):
    calls = []
    _patch_common(monkeypatch, lambda name, **kw: calls.append((name, kw)) or {"started": True})
    events._on_data_updated({})
    assert calls == []


def test_readiness_failure_still_allows_publisher(monkeypatch):
    # Si el recompute falla, el handler no debe propagar (protege al publicador del evento).
    monkeypatch.setattr(events, "SessionLocal", lambda: _DummyDB())

    def _boom_recompute(db):
        raise RuntimeError("readiness roto")
    monkeypatch.setattr(events, "recompute_readiness", _boom_recompute)
    monkeypatch.setattr(ops_service, "trigger", lambda name, **kw: {"started": True})
    events._on_data_updated({})  # no raise
