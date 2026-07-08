"""Tests de la frescura de decisiones de TPM (avisa si no aparece un comunicado a tiempo)."""
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from shared.database.base import Base
from shared.auth.models import User, UserRole
from shared.notifications.service import Notification
from shared.settings.models import AppSetting
from shared.operations import freshness as shared_fr
from modules.macro_monitor.comunicados import freshness as fr
from modules.macro_monitor.comunicados.models import ComunicadoTPM


@pytest.fixture()
def db():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False},
                           poolclass=StaticPool)
    Base.metadata.create_all(engine, tables=[
        ComunicadoTPM.__table__, User.__table__, Notification.__table__, AppSetting.__table__,
    ])
    s = sessionmaker(bind=engine)()
    try:
        yield s
    finally:
        s.close()


def _now():
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _admin(db):
    u = User(email="a@x.com", password_hash="x", full_name="A", role=UserRole.admin, is_active=True)
    db.add(u)
    db.commit()
    return u.id


def _seed(db, date_str, status="ok"):
    db.add(ComunicadoTPM(article_id=hash(date_str) % 100000, string_id="x", title="t",
                         decision_date=date_str, action="hold", tpm_level=5.25, status=status))
    db.commit()


def test_registered_in_shared_auditor():
    assert fr.audit_comunicados_freshness in shared_fr._EXTRA_AUDITS


def test_stale_decision_alerts(db):
    uid = _admin(db)
    old = (_now() - timedelta(days=70)).strftime("%Y-%m-%d")  # >45d → atrasado
    _seed(db, old)
    assert fr.audit_comunicados_freshness(db, [uid], _now()) == ["comunicados_tpm"]
    assert db.query(Notification).filter_by(user_id=uid).count() == 1


def test_recent_decision_no_alert(db):
    uid = _admin(db)
    _seed(db, (_now() - timedelta(days=20)).strftime("%Y-%m-%d"))  # dentro de la cadencia
    assert fr.audit_comunicados_freshness(db, [uid], _now()) == []
    assert db.query(Notification).count() == 0


def test_never_ingested_no_alert(db):
    uid = _admin(db)
    assert fr.audit_comunicados_freshness(db, [uid], _now()) == []


def test_errored_only_no_alert(db):
    # Una decisión 'error' no cuenta como ingerida con éxito → no hay latest ok.
    uid = _admin(db)
    _seed(db, (_now() - timedelta(days=70)).strftime("%Y-%m-%d"), status="error")
    assert fr.audit_comunicados_freshness(db, [uid], _now()) == []


def test_dedups_then_clears_on_recovery(db):
    uid = _admin(db)
    _seed(db, (_now() - timedelta(days=70)).strftime("%Y-%m-%d"))
    fr.audit_comunicados_freshness(db, [uid], _now())          # 1er aviso
    fr.audit_comunicados_freshness(db, [uid], _now())          # dedup
    assert db.query(Notification).count() == 1
    _seed(db, (_now() - timedelta(days=1)).strftime("%Y-%m-%d"))  # decisión nueva y fresca
    fr.audit_comunicados_freshness(db, [uid], _now())          # limpia el marcador
    assert db.query(AppSetting).filter_by(key=shared_fr._alert_key("comunicados_tpm")).count() == 0
