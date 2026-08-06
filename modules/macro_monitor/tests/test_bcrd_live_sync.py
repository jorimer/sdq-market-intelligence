"""El consumo recurrente del API del BCRD: escalar la credencial muerta y avisarlo.

El API del BCRD desactiva la cuenta por inactividad y devuelve el rechazo como error de
APLICACIÓN (HTTP 500 con ``success:false``), indistinguible de un token mal copiado. Antes,
``_fetch_live`` se lo tragaba por variable y la ingesta terminaba "exitosa" con cero
observaciones: la fuente quedaba caída sin dejar rastro. Estos tests fijan el contrato
contrario — sin dato y con rechazo de credencial, la corrida FALLA y avisa.
"""
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import shared.data.bcrd_client as bcrd_mod
import shared.settings.models  # noqa: F401 — registra app_settings antes del create_all
from shared.auth.models import User, UserRole
from shared.data.bcrd_api import BcrdApiError
from shared.data.bcrd_client import BCRDClient
from shared.database.base import Base
from shared.notifications.service import Notification  # noqa: F401 — registra notifications
from shared.operations.service import OPERATIONS, Operation
from shared.settings.models import AppSetting

from modules.macro_monitor.operations import (
    _BCRD_AUTH_ALERT_KEY,
    _bcrd_auth_alert,
    _bcrd_auth_alert_clear,
)

# Una variable con dato real: grupo con ``date`` → value-group (cada métrica es su serie).
_PAYLOAD_OK = {
    "name": "Inflación",
    "values": [{"name": "Inflación", "date": "13/05/2026",
                "values": [{"name": "Interanual", "value": 5.35}]}],
}


@pytest.fixture()
def db():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False},
                           poolclass=StaticPool)
    Base.metadata.create_all(bind=engine)
    session = sessionmaker(bind=engine)()
    yield session
    session.close()


def _dead_credential(*_a, **_k):
    raise BcrdApiError("Credenciales de acceso inválidas", is_auth=True)


# ── El cliente live escala la credencial muerta ───────────────────

def test_dead_credential_raises_instead_of_ingesting_nothing(monkeypatch):
    monkeypatch.setattr(bcrd_mod, "fetch_bcrd_variable", _dead_credential)
    with pytest.raises(BcrdApiError) as exc:
        BCRDClient(mode="live", token="tok").fetch()
    assert exc.value.is_auth


def test_partial_failure_stays_best_effort(monkeypatch):
    """Una variable caída no debe tumbar a las otras tres: solo escalamos el apagón total."""
    def _one_bad(_token, variable, **_k):
        if variable == "monetarias":
            raise BcrdApiError("Credenciales de acceso inválidas", is_auth=True)
        return _PAYLOAD_OK

    monkeypatch.setattr(bcrd_mod, "fetch_bcrd_variable", _one_bad)
    records = BCRDClient(mode="live", token="tok").fetch()
    assert records, "las variables sanas deben seguir ingiriendo"


def test_transport_blackout_does_not_masquerade_as_auth(monkeypatch):
    """Sin rechazo de credencial (p.ej. timeout), se conserva el best-effort histórico:
    devuelve vacío en vez de acusar al token, que mandaría a revisar la clave equivocada."""
    import httpx

    def _timeout(*_a, **_k):
        raise httpx.ConnectTimeout("timeout")

    monkeypatch.setattr(bcrd_mod, "fetch_bcrd_variable", _timeout)
    assert BCRDClient(mode="live", token="tok").fetch() == []


# ── El aviso a los admin ──────────────────────────────────────────

def _admin(db, email="admin@sdq.do"):
    u = User(email=email, password_hash="x", full_name="Admin",
             role=UserRole.admin, is_active=True)
    db.add(u)
    db.commit()
    return u


def test_auth_failure_notifies_admins(db):
    admin = _admin(db)
    _bcrd_auth_alert(db, "Credenciales de acceso inválidas")

    rows = db.query(Notification).filter(Notification.user_id == admin.id).all()
    assert len(rows) == 1
    assert rows[0].type == "error"
    assert rows[0].action_url == "/settings"
    assert "inactividad" in (rows[0].body or "")


def test_alert_is_deduped_then_rearmed_on_recovery(db):
    admin = _admin(db)
    _bcrd_auth_alert(db, "Credenciales de acceso inválidas")
    _bcrd_auth_alert(db, "Credenciales de acceso inválidas")
    assert db.query(Notification).filter(Notification.user_id == admin.id).count() == 1

    # El acceso vuelve → se limpia el marcador y una recaída avisa de inmediato.
    _bcrd_auth_alert_clear(db)
    assert db.query(AppSetting).filter(AppSetting.key == _BCRD_AUTH_ALERT_KEY).first() is None
    _bcrd_auth_alert(db, "Credenciales de acceso inválidas")
    assert db.query(Notification).filter(Notification.user_id == admin.id).count() == 2


def test_viewer_is_not_notified(db):
    """El aviso es accionable solo por quien puede tocar la credencial."""
    viewer = User(email="viewer@sdq.do", password_hash="x", full_name="V",
                  role=UserRole.viewer, is_active=True)
    db.add(viewer)
    db.commit()
    _bcrd_auth_alert(db, "Credenciales de acceso inválidas")
    assert db.query(Notification).filter(Notification.user_id == viewer.id).count() == 0


# ── La agenda ─────────────────────────────────────────────────────

def test_macro_live_sync_is_registered_daily():
    """Diaria y sin params: se auto-agenda en el deploy (seed_default_schedules). Es el único
    consumo recurrente del token — sin ella la cuenta del API muere por inactividad."""
    saved = dict(OPERATIONS)
    OPERATIONS.clear()
    try:
        from modules.macro_monitor.operations import register
        register()
        op = OPERATIONS["macro-live-sync"]
        assert isinstance(op, Operation)
        assert op.default_interval_hours == 24
        assert not op.needs_params
    finally:
        OPERATIONS.clear()
        OPERATIONS.update(saved)
