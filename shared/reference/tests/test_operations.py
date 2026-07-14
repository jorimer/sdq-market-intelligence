"""La operación de consola ``dgii-contribuyentes-sync`` queda registrada (manual) y su
runner cablea al sync."""
import shared.reference.dgii_sync as sync_mod
import shared.reference.operations as ops_mod
from shared.operations import OPERATIONS


def test_operacion_registrada_manual():
    op = OPERATIONS["dgii-contribuyentes-sync"]
    assert op.default_interval_hours == 0          # manual, no auto-agendada
    assert not op.needs_params
    assert "DGII" in op.label


def test_runner_cablea_al_sync(monkeypatch):
    llamado = {}

    class _DummyDB:
        def close(self):
            llamado["closed"] = True

    monkeypatch.setattr(ops_mod, "SessionLocal", lambda: _DummyDB())
    monkeypatch.setattr(sync_mod, "dgii_contribuyentes_sync",
                        lambda db: {"corte": "2026-01-29", "subclases": 3, "touched": 3})

    phases = []
    res = ops_mod._run_dgii_contribuyentes_sync(None, "u1", phases.append)
    assert res["subclases"] == 3
    assert llamado.get("closed") is True           # cerró la sesión
    assert phases                                  # reportó fase
