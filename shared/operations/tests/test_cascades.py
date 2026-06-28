"""Tests de las cascadas por dependencia (Capa 1 del lazo de auto-mejora).

Una operación que termina con éxito dispara las que declara en ``triggers`` —el dato
nuevo re-puntúa y re-valida solo, sin disparo manual—. Aquí se prueba la mecánica
(`_fire_cascade`) y el grafo declarado del eje sectorial.
"""
import pytest

import shared.operations.service as svc
from shared.operations.service import OPERATIONS, Operation, register_operation


@pytest.fixture()
def temp_ops():
    saved = dict(OPERATIONS)
    OPERATIONS.clear()
    try:
        yield
    finally:
        OPERATIONS.clear()
        OPERATIONS.update(saved)


def test_cascade_fires_each_downstream_with_cascade_origin(monkeypatch, temp_ops):
    register_operation(Operation("up", "Up", "d", lambda *a: {}, 24,
                                 triggers=["down-a", "down-b"]))
    register_operation(Operation("down-a", "A", "d", lambda *a: {}, 0))
    register_operation(Operation("down-b", "B", "d", lambda *a: {}, 0))
    calls = []
    monkeypatch.setattr(svc, "trigger",
                        lambda name, origin="manual", user_id=None, params=None:
                        (calls.append((name, origin)), {"started": True})[1])
    svc._fire_cascade("up")
    assert calls == [("down-a", "cascade"), ("down-b", "cascade")]


def test_no_triggers_fires_nothing(monkeypatch, temp_ops):
    register_operation(Operation("solo", "Solo", "d", lambda *a: {}, 24))
    calls = []
    monkeypatch.setattr(svc, "trigger",
                        lambda *a, **k: calls.append(a) or {"started": True})
    svc._fire_cascade("solo")
    assert calls == []


def test_cascade_isolated_from_downstream_failures(monkeypatch, temp_ops):
    """Un fallo al encadenar (downstream desconocido o excepción) no propaga: la corrida
    de arriba ya terminó bien y no debe romperse."""
    register_operation(Operation("up", "Up", "d", lambda *a: {}, 24,
                                 triggers=["missing", "ok"]))
    register_operation(Operation("ok", "Ok", "d", lambda *a: {}, 0))
    seen = []

    def fake_trigger(name, origin="manual", user_id=None, params=None):
        if name == "missing":
            return {"started": False, "reason": "Operación desconocida: missing"}
        seen.append(name)
        return {"started": True}

    monkeypatch.setattr(svc, "trigger", fake_trigger)
    svc._fire_cascade("up")  # no levanta
    assert seen == ["ok"]


def test_sector_intel_cascade_graph_is_wired():
    """El grafo del eje sectorial: las 5 fuentes → sector-snapshot → sector-gate-e.
    El recompute de readiness ya corre por el evento sector.updated (no por cascada)."""
    import modules.sector_intel.operations as ops
    ops.register()  # idempotente
    for src in ("bcrd-sectores-sync", "wgi-sectorial-sync", "encft-empleo-sync",
                "enae-sync", "tss-salario-sync"):
        assert OPERATIONS[src].triggers == ["sector-snapshot"], src
    assert OPERATIONS["sector-snapshot"].triggers == ["sector-gate-e"]
    # acíclico: el backtest no re-dispara nada (hoja del grafo)
    assert OPERATIONS["sector-gate-e"].triggers == []
