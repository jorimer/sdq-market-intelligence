"""La frescura de la TPM escribe el aviso y su marcador de dedup JUNTOS, o ninguno.

Es una auditoría CONTRIBUIDA a `data-freshness-audit` con su propio bucle de avisos: el
arreglo de `shared/operations/freshness.py` no la alcanza. Mismo defecto que #1165 — si el
marcador no entraba, los avisos por admin ya estaban comprometidos y se repetían cada día.
"""
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from modules.macro_monitor.comunicados import freshness as fr
from modules.macro_monitor.comunicados.models import ComunicadoTPM
from shared.auth.models import User, UserRole
from shared.database.base import Base
from shared.notifications.service import Notification
from shared.notifications.tests.rechazo import marcador, rechaza
from shared.settings.models import AppSetting


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


def test_si_el_marcador_no_persiste_no_queda_NINGUN_aviso(db):
    ahora = datetime.now(timezone.utc).replace(tzinfo=None)
    admins = [User(email=f"a{i}@x.com", password_hash="x", full_name="A",
                   role=UserRole.admin, is_active=True) for i in range(2)]
    db.add_all(admins)
    db.add(ComunicadoTPM(article_id=1, string_id="x", title="t", action="hold",
                         decision_date=(ahora - timedelta(days=70)).strftime("%Y-%m-%d"),
                         tpm_level=5.25, status="ok"))
    db.commit()
    uids = [u.id for u in admins]

    with rechaza(db, marcador("freshness_alert")) as rechazos:
        avisados = fr.audit_comunicados_freshness(db, uids, ahora)
    assert rechazos, "la base nunca rechazó el marcador: el test no prueba nada"
    assert avisados == []
    assert db.query(Notification).count() == 0

    # La base vuelve a aceptar: un aviso por admin, UNA vez, y la siguiente auditoría calla.
    assert fr.audit_comunicados_freshness(db, uids, ahora) == [fr._KEY]
    assert fr.audit_comunicados_freshness(db, uids, ahora) == []
    assert db.query(Notification).count() == 2
