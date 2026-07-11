"""Tras un evento de datos, el suscriptor de products dispara el re-calentado de la caché
(op en background, deduped) además de recalcular readiness — sin romper si el disparo falla."""
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


def test_data_event_triggers_prewarm(monkeypatch):
    calls = []
    _patch_common(monkeypatch, lambda name, **kw: calls.append((name, kw)) or {"started": True})
    events._on_data_updated({})
    assert calls == [("prewarm-report-cache", {"origin": "cascade", "user_id": None})]


def test_prewarm_dedup_is_logged_not_raised(monkeypatch):
    # Si ya está en curso (dedup), trigger devuelve started=False → no revienta.
    _patch_common(monkeypatch, lambda name, **kw: {"started": False, "reason": "ya en curso"})
    events._on_data_updated({})  # no raise


def test_prewarm_trigger_failure_does_not_break_publisher(monkeypatch):
    def _boom(name, **kw):
        raise RuntimeError("cola caída")
    _patch_common(monkeypatch, _boom)
    events._on_data_updated({})  # el fallo del warm se traga; el publicador no se rompe


def test_readiness_failure_still_allows_publisher(monkeypatch):
    # Si el recompute falla, el handler no debe propagar (protege al publicador del evento).
    monkeypatch.setattr(events, "SessionLocal", lambda: _DummyDB())

    def _boom_recompute(db):
        raise RuntimeError("readiness roto")
    monkeypatch.setattr(events, "recompute_readiness", _boom_recompute)
    monkeypatch.setattr(ops_service, "trigger", lambda name, **kw: {"started": True})
    events._on_data_updated({})  # no raise
