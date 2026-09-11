"""La auditoría de frescura escribe el aviso y su marcador de dedup JUNTOS, o ninguno.

Mismo defecto que el de las alertas (#1165), en el consumidor original del buzón: el bucle
comprometía un aviso por admin y recién después el marcador. Si el marcador no entraba, los
avisos quedaban escritos y la auditoría siguiente —diaria— los repetía, uno por admin, cada
día, mientras la condición siguiera rota.

Los cuatro sitios que avisan desde `shared/operations/` se prueban por separado: comparten
la fachada `_mark_notified`, pero cada uno tiene su propio bucle, y arreglar uno no arregla
los demás. La regla general la vigila `shared/tests/test_aviso_y_marcador_en_una_transaccion.py`.
"""
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from shared.auth.models import User, UserRole
from shared.database.base import Base
from shared.notifications.service import Notification
from shared.notifications.tests.rechazo import marcador, rechaza
from shared.operations import freshness as fr
from shared.operations.models import OperationRun, OperationSchedule
from shared.operations.service import OPERATIONS, Operation, register_operation
from shared.publications.models import Publication
from shared.settings.models import AppSetting

PREFIJO = "freshness_alert"


@pytest.fixture()
def db():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False},
                           poolclass=StaticPool)
    Base.metadata.create_all(engine, tables=[
        OperationSchedule.__table__, OperationRun.__table__, AppSetting.__table__,
        User.__table__, Notification.__table__, Publication.__table__,
    ])
    s = sessionmaker(bind=engine)()
    try:
        yield s
    finally:
        s.close()


@pytest.fixture()
def una_operacion():
    """El registro reducido a UNA operación recurrente que nunca corrió (→ atrasada)."""
    previas = dict(OPERATIONS)
    OPERATIONS.clear()
    register_operation(Operation("t-recurring", "Recurrente", "d", lambda *a: {}, 24))
    try:
        yield "t-recurring"
    finally:
        OPERATIONS.clear()
        OPERATIONS.update(previas)


def _admins(db, n=2):
    """Dos admins, a propósito: con uno solo, «un aviso por admin comprometido antes del
    marcador» y «el aviso entero comprometido antes del marcador» no se distinguen."""
    us = [User(email=f"a{i}@x.com", password_hash="x", full_name="A",
               role=UserRole.admin, is_active=True) for i in range(n)]
    db.add_all(us)
    db.commit()
    return [u.id for u in us]


def _avisos(db, titulo):
    return db.query(Notification).filter(Notification.title.startswith(titulo)).count()


def _ahora():
    return datetime.now(timezone.utc).replace(tzinfo=None)


def test_operacion_atrasada_si_el_marcador_no_persiste_no_queda_NINGUN_aviso(db, una_operacion):
    _admins(db)
    with rechaza(db, marcador(PREFIJO)) as rechazos:
        res = fr.run_freshness_audit(db)
    assert una_operacion in res["overdue"], "la fixture no ejercita el aviso"
    assert rechazos, "la base nunca rechazó el marcador: el test no prueba nada"
    assert res["notified"] == 0
    assert _avisos(db, "Dato desactualizado") == 0

    # La base vuelve a aceptar: un aviso por admin, UNA vez, y la siguiente auditoría calla.
    fr.run_freshness_audit(db)
    fr.run_freshness_audit(db)
    assert _avisos(db, "Dato desactualizado") == 2


def test_publicacion_vieja_si_el_marcador_no_persiste_no_queda_NINGUN_aviso(db):
    uids = _admins(db)
    db.add(Publication(report_key="politica_monetaria", report_name="IPoM", period="p",
                       status="ok", created_at=_ahora() - timedelta(days=200)))
    db.commit()

    with rechaza(db, marcador(PREFIJO)) as rechazos:
        alertadas = fr._audit_publications(db, uids, _ahora())
    assert rechazos, "la base nunca rechazó el marcador: el test no prueba nada"
    assert alertadas == []
    assert _avisos(db, "Publicación por verificar") == 0

    assert fr._audit_publications(db, uids, _ahora()) == ["politica_monetaria"]
    assert fr._audit_publications(db, uids, _ahora()) == []
    assert _avisos(db, "Publicación por verificar") == 2


def test_rating_soberano_si_el_marcador_no_persiste_no_queda_NINGUN_aviso(db):
    from shared.contracts.sovereign_ratings import save_sovereign_ratings

    uids = _admins(db)
    save_sovereign_ratings(db, {"DO": {"sp": {"rating": "BB", "action_date": "2022-12-19"}}})
    ahora = datetime(2026, 7, 1, tzinfo=timezone.utc)

    with rechaza(db, marcador(PREFIJO)) as rechazos:
        propuestos = fr._audit_sovereign_ratings(db, uids, ahora)
    assert rechazos, "la base nunca rechazó el marcador: el test no prueba nada"
    assert propuestos == []
    assert _avisos(db, "Rating soberano por verificar") == 0

    assert fr._audit_sovereign_ratings(db, uids, ahora) == ["DO"]
    assert fr._audit_sovereign_ratings(db, uids, ahora) == []
    assert _avisos(db, "Rating soberano por verificar") == 2


# ── Fuente congelada: necesita el catálogo real, así que va con todas las tablas ──

@pytest.fixture()
def db_completa():
    import modules.energy_intel.models.models  # noqa: F401 — registra EnergyScore

    engine = create_engine("sqlite://", connect_args={"check_same_thread": False},
                           poolclass=StaticPool)
    Base.metadata.create_all(engine)
    s = sessionmaker(bind=engine)()
    try:
        yield s
    finally:
        s.close()


def test_fuente_congelada_si_el_marcador_no_persiste_no_queda_NINGUN_aviso(db_completa):
    from modules.energy_intel.models.models import EnergyScore
    from shared.operations.fuentes_congeladas import auditar_fuentes_de_los_ejes

    db = db_completa
    uids = _admins(db)
    # La fuente muerta real de la SIE: última anualidad 2023 (ver test_fuentes_congeladas).
    db.add(EnergyScore(period="2023", energy_score=61.0, band="B", coverage=1.0,
                       capacity_mw=5000.0, capacity_score=60.0, service_score=62.0,
                       transition_score=61.0, breakdown={}))
    db.commit()

    with rechaza(db, marcador(PREFIJO)) as rechazos:
        avisados = auditar_fuentes_de_los_ejes(db, uids, _ahora())
    assert rechazos, "la base nunca rechazó el marcador: el test no prueba nada"
    assert "energy" not in avisados
    assert _avisos(db, "Fuente sin publicar: energy") == 0

    assert "energy" in auditar_fuentes_de_los_ejes(db, uids, _ahora())
    assert "energy" not in auditar_fuentes_de_los_ejes(db, uids, _ahora())
    assert _avisos(db, "Fuente sin publicar: energy") == 2
