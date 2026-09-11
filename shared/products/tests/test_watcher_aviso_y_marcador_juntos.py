"""«Listo para publicar»: el aviso y su marcador se escriben JUNTOS, o ninguno.

Acá el orden era el INVERSO al de #1165 y el riesgo, peor: el marcador se comprometía antes
de avisar. Si el aviso no entraba, quedaba el marcador —y este marcador **no vence por
tiempo** (`_SIN_VENCIMIENTO`)—, así que ese cruce de publicabilidad no se avisaba nunca más
mientras el nivel siguiera publicable. Un silencio permanente que ningún log repite.
"""
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import shared.products.service as svc
from shared.auth.models import User, UserRole
from shared.database.base import Base
from shared.notifications.service import Notification
from shared.notifications.tests.rechazo import marcador, notificacion, rechaza
from shared.products.models import ProductActivation, ProductReadiness
from shared.products.tiers import ProductTier
from shared.settings.models import AppSetting

CRUCE = [("banking", ProductTier.insight, 0.9), ("banking", ProductTier.deep_dive, 0.9)]


@pytest.fixture()
def db():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False},
                           poolclass=StaticPool)
    Base.metadata.create_all(engine, tables=[
        ProductReadiness.__table__, ProductActivation.__table__,
        User.__table__, Notification.__table__, AppSetting.__table__])
    s = sessionmaker(bind=engine)()
    try:
        yield s
    finally:
        s.close()


@pytest.fixture()
def admins(db):
    us = [User(email=f"a{i}@x.com", password_hash="x", full_name="A",
               role=UserRole.admin, is_active=True) for i in range(2)]
    db.add_all(us)
    db.commit()
    return us


def _marcadores(db):
    return db.query(AppSetting).filter(AppSetting.key.startswith("readiness_cross:")).count()


def _como_lo_llama_recompute(db, up):
    """Lo que hace `recompute_readiness` con el aviso: si levanta, rollback y seguir.

    El rollback no es decorativo. Un `before_flush` que levanta NO invalida la sesión: la
    fila rechazada queda pendiente y el siguiente `count()` la flushea. Con un `suppress` a
    secas, el test medía ese artefacto (una notificación «persistida» que en producción el
    rollback del llamador descarta) y no el defecto real, que es el marcador."""
    try:
        svc._notify_publishable_transitions(db, up=up, down=[])
    except Exception:  # noqa: BLE001
        db.rollback()


def test_si_el_aviso_no_persiste_no_queda_el_marcador_que_lo_silencia_para_siempre(db, admins):
    with rechaza(db, notificacion) as rechazos:
        _como_lo_llama_recompute(db, CRUCE)
    assert rechazos, "la base nunca rechazó el aviso: el test no prueba nada"
    assert db.query(Notification).count() == 0
    assert _marcadores(db) == 0

    # El mismo cruce, con la base aceptando: se avisa UNA vez por admin, y el siguiente calla.
    svc._notify_publishable_transitions(db, up=CRUCE, down=[])
    svc._notify_publishable_transitions(db, up=CRUCE, down=[])
    assert db.query(Notification).count() == 2
    assert _marcadores(db) == 2


def test_si_el_marcador_no_persiste_no_queda_NINGUN_aviso(db, admins):
    """El otro lado de la misma transacción. Con el orden viejo (marcar primero) pasaba
    solo; se escribe para que invertir el orden no reabra #1165 por este sitio."""
    with rechaza(db, marcador("readiness_cross")) as rechazos:
        _como_lo_llama_recompute(db, CRUCE)
    assert rechazos, "la base nunca rechazó el marcador: el test no prueba nada"
    assert db.query(Notification).count() == 0

    svc._notify_publishable_transitions(db, up=CRUCE, down=[])
    svc._notify_publishable_transitions(db, up=CRUCE, down=[])
    assert db.query(Notification).count() == 2
