"""La degradación de narrativa que BLOQUEA una entrega premium queda en el historial de la
Consola de Operaciones (que ve el admin/superadmin) como un ``OperationRun`` con estado error.
"""
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from shared.auth.models import User  # noqa: F401 — registra 'users' para el FK de OperationRun
from shared.database.base import Base
from shared.events.event_bus import event_bus
from shared.operations.models import OperationRun  # noqa: F401 — registra la tabla
from shared.operations.service import record_incident, recent_runs


@pytest.fixture()
def db():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False},
                           poolclass=StaticPool)
    Base.metadata.create_all(engine, tables=[User.__table__, OperationRun.__table__])
    Session = sessionmaker(bind=engine)
    s = Session()
    try:
        yield s, Session
    finally:
        s.close()


def test_record_incident_appears_in_history(db):
    s, _ = db
    record_incident(s, "narrative-degraded",
                    summary={"sector_key": "insurance", "tier": "deep_dive"},
                    error="degradado")
    hist = recent_runs(s)
    assert len(hist) == 1
    row = hist[0]
    assert row["operation"] == "narrative-degraded"
    assert row["status"] == "error"                     # chip 'alert' en la consola
    assert row["summary"]["sector_key"] == "insurance"
    assert row["started_at"] and row["finished_at"]     # incidente terminal (no 'running')


def test_blocked_event_writes_incident_via_subscriber(db, monkeypatch):
    """Emitir un evento bloqueado (con el suscriptor de ops enganchado) escribe la fila."""
    s, Session = db
    # `_record_ops_incident` abre su propia SessionLocal → apuntarla al engine del test.
    monkeypatch.setattr("shared.database.session.SessionLocal", Session)
    event_bus.clear()
    from shared.narrative.degradation_events import (
        emit_narrative_degraded,
        subscribe_narrative_degradation_events,
    )
    subscribe_narrative_degradation_events()
    try:
        emit_narrative_degraded(surface="products", sector_key="pension", tier="deep_dive",
                                sections=["assessment", "peer_positioning"], blocked=True,
                                scope="afp_x", period="2025")
        hist = recent_runs(s)
        assert len(hist) == 1 and hist[0]["operation"] == "narrative-degraded"
        assert hist[0]["status"] == "error"
        assert hist[0]["summary"]["count"] == 1
        assert hist[0]["summary"]["last"]["section_count"] == 2
    finally:
        event_bus.clear()


def test_multiple_blocked_events_group_into_one_row(db, monkeypatch):
    """Varias degradaciones dentro de la ventana → UNA fila, con conteo acumulado."""
    s, Session = db
    monkeypatch.setattr("shared.database.session.SessionLocal", Session)
    event_bus.clear()
    from shared.narrative.degradation_events import (
        emit_narrative_degraded,
        subscribe_narrative_degradation_events,
    )
    subscribe_narrative_degradation_events()
    try:
        for _ in range(3):
            emit_narrative_degraded(surface="products", sector_key="insurance",
                                    tier="deep_dive", sections=["a"], blocked=True,
                                    scope="sr", period="2025")
        emit_narrative_degraded(surface="products", sector_key="pension", tier="deep_dive",
                                sections=["a", "b"], blocked=True, scope="afp_x", period="2025")
        hist = recent_runs(s)
        assert len(hist) == 1                       # 4 degradaciones -> 1 sola fila
        summ = hist[0]["summary"]
        assert summ["count"] == 4
        assert summ["by_target"] == {"insurance/deep_dive": 3, "pension/deep_dive": 1}
        assert "4 degradaciones" in hist[0]["error"]
    finally:
        event_bus.clear()


def test_open_pulse_event_writes_no_incident(db, monkeypatch):
    """La degradación de nivel abierto (Pulse) NO inunda el historial: solo log."""
    s, Session = db
    monkeypatch.setattr("shared.database.session.SessionLocal", Session)
    event_bus.clear()
    from shared.narrative.degradation_events import (
        emit_narrative_degraded,
        subscribe_narrative_degradation_events,
    )
    subscribe_narrative_degradation_events()
    try:
        emit_narrative_degraded(surface="products", sector_key="pension", tier="pulse",
                                sections=["pension_pulse"], blocked=False, scope=None,
                                period="2025")
        assert recent_runs(s) == []
    finally:
        event_bus.clear()
