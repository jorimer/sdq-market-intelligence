"""Watchlist de alertas (fase A) — validación, acceso y la sentinela de ``subject``.

Lo que estos tests protegen, en orden de qué tan caro sale si se rompe:

1. **Acceso**: una vigilancia de un eje que el cliente no tiene filtra dato que se le cobra
   a otro — y se re-verifica en la ENTREGA, no solo al suscribir.
2. **La sentinela**: con ``subject`` nullable, dos «todo el eje» del mismo usuario conviven
   (NULL ≠ NULL en SQLite y en Postgres) y el cliente recibe cada alerta duplicada.
3. **Canal mudo**: aceptar un canal sin entrega deja al cliente esperando avisos que nunca
   salen. No falla: desaparece.
"""
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import shared.alerts.router as alerts_router
import shared.alerts.service as service
from shared.alerts.models import TODO_EL_EJE, AlertSubscription
from shared.auth.dependencies import get_current_user
from shared.auth.models import AccessTier, User, UserRole
from shared.database.base import Base
from shared.database.session import get_db
from shared.products.models import ProductActivation, ProductEntitlement, Subscription
from shared.products.tiers import ProductTier

# Ejes reales del catálogo (`shared.products.registry.PRODUCT_CATALOG`), no inventados: si
# alguno se renombra, estos tests tienen que enterarse.
EJE = "banking"
EJE_FIJO = "macro"


@pytest.fixture()
def db():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False},
                           poolclass=StaticPool)
    Base.metadata.create_all(engine, tables=[
        User.__table__, AlertSubscription.__table__, ProductActivation.__table__,
        ProductEntitlement.__table__, Subscription.__table__])
    s = sessionmaker(bind=engine)()
    try:
        yield s
    finally:
        s.close()


def _user(db, tier=AccessTier.free, uid="u1", email=None, active=True):
    u = User(id=uid, email=email or f"{uid}@sdq.do", password_hash="x", full_name="Test",
             role=UserRole.viewer, tier=tier, is_active=active)
    db.add(u)
    db.commit()
    return u


def _activar(db, sector, *tiers):
    for t in tiers:
        db.add(ProductActivation(sector_key=sector, tier=t.value, is_active=True))
    db.commit()


class _ProductoConSujetos:
    """Doble de un producto que declara sujetos elegibles (banca elige entidad)."""

    def scope_options(self):
        return [{"value": "banco-a", "label": "Banco A", "group": "multiple"},
                {"value": "banco-b", "label": "Banco B", "group": "multiple"}]


class _ProductoSujetoFijo:
    """Doble de un producto de sujeto ÚNICO: no implementa ``scope_options``."""


@pytest.fixture()
def productos(monkeypatch):
    """Resuelve ``get_product`` sin tocar los módulos de sector reales."""
    mapa = {EJE: _ProductoConSujetos(), EJE_FIJO: _ProductoSujetoFijo()}
    monkeypatch.setattr(service, "get_product", lambda key, db=None: mapa.get(key))
    return mapa


def _client(db, user):
    app = FastAPI()
    app.include_router(alerts_router.router, prefix="/api/v1/alerts")
    app.dependency_overrides[get_db] = lambda: db
    app.dependency_overrides[get_current_user] = lambda: user
    return TestClient(app)


# ── Alta y validación ────────────────────────────────────────────────────────

def test_vigilar_el_eje_entero_es_pulse(db, productos):
    """Sin sujeto, el nivel exigido es Pulse: un tier free alcanza."""
    _activar(db, EJE, ProductTier.pulse)
    u = _user(db)
    r = _client(db, u).post("/api/v1/alerts/subscriptions", json={"sector_key": EJE})
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["subject"] is None          # la sentinela NO se filtra a la API
    assert body["tier_requerido"] == "pulse"
    assert body["channels"] == ["inapp"]


def test_vigilar_una_entidad_nombrada_exige_insight(db, productos):
    """Con sujeto, el nivel es Insight — y un free recibe 402 con el upsell, no un 500."""
    _activar(db, EJE, ProductTier.pulse, ProductTier.insight)
    u = _user(db)
    r = _client(db, u).post("/api/v1/alerts/subscriptions",
                            json={"sector_key": EJE, "subject": "banco-a"})
    assert r.status_code == 402
    assert r.json()["detail"]["required_tier"]


def test_entidad_nombrada_con_tier_suficiente(db, productos):
    _activar(db, EJE, ProductTier.insight)
    u = _user(db, tier=AccessTier.pro)
    r = _client(db, u).post("/api/v1/alerts/subscriptions",
                            json={"sector_key": EJE, "subject": "banco-b"})
    assert r.status_code == 201, r.text
    assert r.json()["subject"] == "banco-b"
    assert r.json()["tier_requerido"] == "insight"


def test_sujeto_fuera_del_universo_del_producto(db, productos):
    _activar(db, EJE, ProductTier.insight)
    u = _user(db, tier=AccessTier.pro)
    r = _client(db, u).post("/api/v1/alerts/subscriptions",
                            json={"sector_key": EJE, "subject": "banco-que-no-existe"})
    assert r.status_code == 422
    assert "no es un sujeto válido" in r.json()["detail"]


def test_eje_de_sujeto_fijo_rechaza_sujeto_y_dice_por_que(db, productos):
    """Un producto sin ``scope_options`` es de sujeto único: pedirle una entidad es un error
    del cliente, y el mensaje tiene que decirle qué hacer en su lugar."""
    _activar(db, EJE_FIJO, ProductTier.insight)
    u = _user(db, tier=AccessTier.pro)
    r = _client(db, u).post("/api/v1/alerts/subscriptions",
                            json={"sector_key": EJE_FIJO, "subject": "DOM"})
    assert r.status_code == 422
    assert "sujeto único" in r.json()["detail"]


def test_eje_sin_implementacion_no_se_puede_vigilar(db, productos):
    """Suscribirse a un eje que no produce nada es una promesa que no se puede cumplir."""
    u = _user(db)
    r = _client(db, u).post("/api/v1/alerts/subscriptions", json={"sector_key": "energy"})
    assert r.status_code == 422
    assert "todavía no produce alertas" in r.json()["detail"]


def test_eje_fuera_del_catalogo(db, productos):
    u = _user(db)
    r = _client(db, u).post("/api/v1/alerts/subscriptions", json={"sector_key": "criptos"})
    assert r.status_code == 422
    assert "no está en el catálogo" in r.json()["detail"]


def test_canal_sin_entrega_se_rechaza_declarando_el_motivo(db, productos):
    """Email llega en la fase C. Aceptarlo ahora dejaría al cliente esperando avisos que
    nunca salen — y un canal mudo no falla, desaparece."""
    _activar(db, EJE, ProductTier.pulse)
    u = _user(db)
    r = _client(db, u).post("/api/v1/alerts/subscriptions",
                            json={"sector_key": EJE, "channels": ["email"]})
    assert r.status_code == 422
    assert "todavía no entrega" in r.json()["detail"]


def test_disparador_desconocido(db, productos):
    _activar(db, EJE, ProductTier.pulse)
    u = _user(db)
    r = _client(db, u).post("/api/v1/alerts/subscriptions",
                            json={"sector_key": EJE, "rule_codes": ["telepatia"]})
    assert r.status_code == 422
    assert "telepatia" in r.json()["detail"]


def test_severidad_y_digest_invalidos(db, productos):
    _activar(db, EJE, ProductTier.pulse)
    u = _user(db)
    c = _client(db, u)
    assert c.post("/api/v1/alerts/subscriptions",
                  json={"sector_key": EJE, "min_severity": "urgentisima"}).status_code == 422
    assert c.post("/api/v1/alerts/subscriptions",
                  json={"sector_key": EJE, "digest": "cada rato"}).status_code == 422


# ── La sentinela y la unicidad ───────────────────────────────────────────────

def test_todo_el_eje_se_guarda_como_sentinela_no_como_null(db, productos):
    """El UNIQUE (user, sector, subject) solo muerde si ``subject`` NO es nullable: dos NULL
    son distintos entre sí en SQLite y en Postgres."""
    _activar(db, EJE, ProductTier.pulse)
    u = _user(db)
    _client(db, u).post("/api/v1/alerts/subscriptions", json={"sector_key": EJE})
    row = db.query(AlertSubscription).one()
    assert row.subject == TODO_EL_EJE
    assert row.subject is not None


def test_la_base_RECHAZA_dos_vigilancias_iguales(db, productos):
    """El diente del UNIQUE, comprobado sin pasar por el servicio.

    La idempotencia del alta ya evita el duplicado por la vía normal, pero si el UNIQUE no
    muerde, cualquier otro camino a la tabla (una carga, un backfill, una condición de
    carrera entre dos POST) mete la fila gemela y el cliente recibe cada alerta dos veces.
    Con ``subject`` nullable este insert PASA, que es exactamente el defecto.
    """
    from sqlalchemy.exc import IntegrityError

    _activar(db, EJE, ProductTier.pulse)
    u = _user(db)
    service.crear(db, u, sector_key=EJE)
    db.add(AlertSubscription(user_id=u.id, sector_key=EJE, subject=TODO_EL_EJE,
                             channels=["inapp"], min_severity="media", digest="inmediato",
                             active=True))
    with pytest.raises(IntegrityError):
        db.commit()
    db.rollback()


def test_vigilar_dos_veces_es_idempotente_y_reconfigura(db, productos):
    """El botón «Vigilar» no tiene por qué saber si ya existe."""
    _activar(db, EJE, ProductTier.pulse)
    u = _user(db)
    c = _client(db, u)
    a = c.post("/api/v1/alerts/subscriptions", json={"sector_key": EJE})
    b = c.post("/api/v1/alerts/subscriptions",
               json={"sector_key": EJE, "min_severity": "baja", "digest": "diario"})
    assert a.status_code == 201 and b.status_code == 201
    assert a.json()["id"] == b.json()["id"]
    assert db.query(AlertSubscription).count() == 1
    assert b.json()["min_severity"] == "baja"
    assert b.json()["digest"] == "diario"


def test_revigilar_reactiva_una_suspendida(db, productos):
    _activar(db, EJE, ProductTier.pulse)
    u = _user(db)
    c = _client(db, u)
    c.post("/api/v1/alerts/subscriptions", json={"sector_key": EJE})
    row = db.query(AlertSubscription).one()
    row.active, row.suspended_reason = False, "acceso_revocado"
    db.commit()

    c.post("/api/v1/alerts/subscriptions", json={"sector_key": EJE})
    db.refresh(row)
    assert bool(row.active) is True
    assert row.suspended_reason is None


# ── Aislamiento por usuario ──────────────────────────────────────────────────

def test_no_se_ven_ni_se_tocan_vigilancias_ajenas(db, productos):
    """404 y no 403: no se revela que la vigilancia de otro existe."""
    _activar(db, EJE, ProductTier.pulse)
    dueno = _user(db, uid="u1")
    otro = _user(db, uid="u2")
    creada = _client(db, dueno).post("/api/v1/alerts/subscriptions",
                                     json={"sector_key": EJE}).json()

    c = _client(db, otro)
    assert c.get("/api/v1/alerts/subscriptions").json()["subscriptions"] == []
    assert c.patch(f"/api/v1/alerts/subscriptions/{creada['id']}",
                   json={"digest": "diario"}).status_code == 404
    assert c.delete(f"/api/v1/alerts/subscriptions/{creada['id']}").status_code == 404


def test_baja(db, productos):
    _activar(db, EJE, ProductTier.pulse)
    u = _user(db)
    c = _client(db, u)
    sid = c.post("/api/v1/alerts/subscriptions", json={"sector_key": EJE}).json()["id"]
    assert c.delete(f"/api/v1/alerts/subscriptions/{sid}").status_code == 200
    assert db.query(AlertSubscription).count() == 0


# ── El re-chequeo de acceso en la entrega ────────────────────────────────────

def test_entregables_suspende_cuando_cae_el_acceso_y_lo_LISTA(db, productos):
    """Una vigilancia sobrevive al fin del contrato. Sin re-chequeo en la entrega, el
    cliente que se dio de baja sigue recibiendo el producto que dejó de pagar."""
    _activar(db, EJE, ProductTier.insight)
    u = _user(db, tier=AccessTier.pro)
    service.crear(db, u, sector_key=EJE, subject="banco-a")
    sub = db.query(AlertSubscription).one()

    ok, _ = service.entregables(db, [sub])
    assert len(ok) == 1                      # con acceso, entrega

    u.tier = AccessTier.free                 # el cliente se dio de baja
    db.commit()
    ok, suspendidas = service.entregables(db, [sub])
    assert ok == []
    assert suspendidas[0]["motivo"] == "acceso_revocado"

    db.refresh(sub)
    assert bool(sub.active) is False
    assert sub.suspended_reason == "acceso_revocado"   # se persiste el motivo, no se borra


def test_entregables_reanuda_sola_cuando_vuelve_el_acceso(db, productos):
    """Si renueva, vuelve a lo que ya había elegido — sin acordarse de reactivar nada."""
    _activar(db, EJE, ProductTier.insight)
    u = _user(db, tier=AccessTier.pro)
    service.crear(db, u, sector_key=EJE, subject="banco-a")
    sub = db.query(AlertSubscription).one()

    u.tier = AccessTier.free
    db.commit()
    service.entregables(db, [sub])

    u.tier = AccessTier.pro
    db.commit()
    sub.active = True                        # el cliente re-vigila (o lo hace el alta)
    db.commit()
    ok, suspendidas = service.entregables(db, [sub])
    assert len(ok) == 1 and suspendidas == []
    db.refresh(sub)
    assert sub.suspended_reason is None


def test_entregables_suspende_al_usuario_inactivo(db, productos):
    _activar(db, EJE, ProductTier.pulse)
    u = _user(db)
    service.crear(db, u, sector_key=EJE)
    sub = db.query(AlertSubscription).one()
    u.is_active = False
    db.commit()

    ok, suspendidas = service.entregables(db, [sub])
    assert ok == [] and suspendidas[0]["motivo"] == "usuario_inactivo"


# ── La consulta que usará el motor (fase B) ──────────────────────────────────

def test_para_sujeto_trae_la_del_sujeto_y_la_del_eje_entero(db, productos):
    """Quien vigila el eje completo también tiene que enterarse de lo que pasa en un sujeto
    concreto — si no, «vigilar el sistema» no vigila nada."""
    _activar(db, EJE, ProductTier.pulse, ProductTier.insight)
    todo = _user(db, uid="u1")
    puntual = _user(db, uid="u2", tier=AccessTier.pro)
    ajeno = _user(db, uid="u3", tier=AccessTier.pro)
    service.crear(db, todo, sector_key=EJE)
    service.crear(db, puntual, sector_key=EJE, subject="banco-a")
    service.crear(db, ajeno, sector_key=EJE, subject="banco-b")

    alcanzadas = service.para_sujeto(db, EJE, "banco-a")
    assert {s.user_id for s in alcanzadas} == {"u1", "u2"}


def test_para_sujeto_ignora_las_inactivas(db, productos):
    _activar(db, EJE, ProductTier.pulse)
    u = _user(db)
    service.crear(db, u, sector_key=EJE)
    row = db.query(AlertSubscription).one()
    row.active = False
    db.commit()
    assert service.para_sujeto(db, EJE, "banco-a") == []


# ── Catálogo de disparadores ─────────────────────────────────────────────────

def test_el_catalogo_declara_CUALES_tienen_motor_y_cuales_no(db, productos):
    """Un disparador mudo presentado como activo se lee como que no pasó nada; uno activo
    presentado como mudo hace que nadie lo elija. La API tiene que decir cuál es cuál, y
    este test se rompe a propósito cada vez que una fase enchufa un motor nuevo."""
    u = _user(db)
    body = _client(db, u).get("/api/v1/alerts/rules").json()
    por_codigo = {r["codigo"]: r for r in body["rules"]}
    assert set(por_codigo) >= {"umbral", "banda", "brecha", "posicion", "frescura"}

    # Fase B: umbral, banda y brecha ya tienen reglas puras y productor de banca.
    assert all(por_codigo[c]["implementado"] is True for c in ("umbral", "banda", "brecha"))
    # Y el resto sigue declarándose sin motor, en vez de insinuar que suena.
    assert all(por_codigo[c]["implementado"] is False
               for c in ("posicion", "frescura", "publicacion"))

    assert all(r["basis"] for r in body["rules"])      # ninguna regla suena "porque sí"
    assert body["canales_disponibles"] == ["inapp"]
    assert "email" in body["canales_planificados"]
