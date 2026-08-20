"""El canal máquina-a-máquina — y sobre todo a quién NO le llega.

Un webhook de alertas lleva contenido: cifras, nombres de entidad, la procedencia. Mandarlo
a un endpoint equivocado no es un aviso perdido, es una fuga. Los tres guards que importan:

1. **`"*"` no lo arrastra.** Un webhook viejo registrado con «todos los eventos» se suscribió
   a los avisos de «hay dato nuevo», que NO llevan el dato. Dejar que el comodín traiga
   también las alertas le manda contenido que nunca pidió.
2. **Se entrega por DUEÑO, no en difusión.** El webhook de otro cliente no recibe.
3. **La llave revocada corta el canal**, sin que nadie tenga que acordarse de borrar nada.
"""
import datetime as _dt

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from shared.alerts import entrega, motor, service, webhook
from shared.alerts.models import AlertDelivery, AlertEventRow, AlertSubscription
from shared.alerts.reglas import rule_umbral
from shared.auth.models import AccessTier, User, UserRole
from shared.data_api.models import ApiKey, ApiWebhook, ApiWebhookDelivery
from shared.database.base import Base
from shared.notifications.service import Notification
from shared.products.models import ProductActivation, ProductEntitlement, Subscription
from shared.products.tiers import ProductTier
from shared.settings.models import AppSetting

EJE = "banking"


@pytest.fixture()
def db():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False},
                           poolclass=StaticPool)
    Base.metadata.create_all(engine, tables=[
        User.__table__, AlertSubscription.__table__, AlertEventRow.__table__,
        AlertDelivery.__table__, Notification.__table__, AppSetting.__table__,
        ProductActivation.__table__, ProductEntitlement.__table__, Subscription.__table__,
        ApiKey.__table__, ApiWebhook.__table__, ApiWebhookDelivery.__table__])
    s = sessionmaker(bind=engine)()
    try:
        yield s
    finally:
        s.close()


class _Producto:
    """Eje de sujeto FIJO."""


@pytest.fixture(autouse=True)
def entorno(monkeypatch):
    """Captura los envíos en vez de salir a la red."""
    monkeypatch.setattr(service, "get_product",
                        lambda key, db=None: _Producto() if key == EJE else None)
    enviados = []

    def _fake_deliver(db_factory, hook_id, event, payload):
        enviados.append({"hook_id": hook_id, "event": event, "payload": payload})

    import shared.data_api.webhooks as dw
    monkeypatch.setattr(dw, "_deliver", _fake_deliver)
    previos = dict(motor._PRODUCTORES)
    motor._PRODUCTORES.clear()
    yield enviados
    motor._PRODUCTORES.clear()
    motor._PRODUCTORES.update(previos)


def _user(db, uid="u1"):
    u = User(id=uid, email=f"{uid}@sdq.do", password_hash="x", full_name="T",
             role=UserRole.viewer, tier=AccessTier.free, is_active=True)
    db.add(u)
    db.commit()
    return u


def _hook(db, user, *, events=webhook.EVENTO, activo=True, key_activa=True,
          revocada=False, hid="h1", kid="k1"):
    db.add(ApiKey(id=kid, user_id=user.id, name="PMS", prefix=f"sdq_{kid}",
                  secret_hash="h",
                  active=key_activa, revoked_at=(_dt.datetime(2026, 1, 1) if revocada else None)))
    db.add(ApiWebhook(id=hid, api_key_id=kid, url="https://cliente.do/hook",
                      secret="s3cr3t", events=events, active=activo,
                      consecutive_failures=0))
    db.commit()


def _activar(db):
    db.add(ProductActivation(sector_key=EJE, tier=ProductTier.pulse.value, is_active=True))
    db.commit()


def _evento():
    return rule_umbral(
        sector_key=EJE, subject="", sujeto_label="Sistema", periodo="2026-Q2",
        metrica="cobertura", metrica_label="Cobertura de provisiones", valor=91.0,
        umbral=100.0, direccion="por_debajo", severidad="alta",
        basis="crisis RD 2003", procedencia={"cobertura": "live"}, frescura=True)


def _barrer(db, *eventos):
    motor.register_producer(EJE, lambda _db: motor.Produccion(eventos=list(eventos),
                                                              evaluadas=set()))
    return motor.run_alerts_sweep(db)


# ── El comodín NO arrastra las alertas ───────────────────────────────────────

def test_el_comodin_NO_suscribe_a_las_alertas(db):
    """Un webhook viejo con `"*"` pidió los avisos de «hay dato nuevo», que no llevan el
    dato. Arrastrarlo a las alertas le manda contenido que nunca pidió."""
    u = _user(db)
    _hook(db, u, events="*")
    assert webhook.hooks_de(db, u.id) == []
    assert webhook.tiene_canal(db, u.id) is False


def test_nombrarlo_explicitamente_SI_suscribe(db):
    u = _user(db)
    _hook(db, u, events=f"macro.updated,{webhook.EVENTO}")
    assert len(webhook.hooks_de(db, u.id)) == 1
    assert webhook.tiene_canal(db, u.id) is True


# ── Entrega por dueño ────────────────────────────────────────────────────────

def test_solo_recibe_el_DUENO_de_la_vigilancia(db, entorno):
    """Una alerta puede nombrar entidades que otro cliente no compró: la difusión sería
    una fuga, no un aviso de más."""
    _activar(db)
    dueno = _user(db, "u1")
    ajeno = _user(db, "u2")
    _hook(db, dueno, hid="h1", kid="k1")
    _hook(db, ajeno, hid="h2", kid="k2")
    service.crear(db, dueno, sector_key=EJE, channels=["inapp", "webhook"])

    _barrer(db, _evento())

    assert [e["hook_id"] for e in entorno] == ["h1"]


def test_una_llave_REVOCADA_corta_el_canal(db, entorno):
    """Sin que nadie tenga que acordarse de borrar el webhook."""
    _activar(db)
    u = _user(db)
    _hook(db, u, revocada=True)
    assert webhook.hooks_de(db, u.id) == []


def test_una_llave_INACTIVA_corta_el_canal(db):
    u = _user(db)
    _hook(db, u, key_activa=False)
    assert webhook.hooks_de(db, u.id) == []


def test_un_webhook_desactivado_no_recibe(db):
    u = _user(db)
    _hook(db, u, activo=False)
    assert webhook.hooks_de(db, u.id) == []


# ── El payload ───────────────────────────────────────────────────────────────

def test_el_aviso_SI_lleva_su_contenido(db, entorno):
    """La divergencia deliberada con el webhook de «hay dato nuevo»: un aviso que no dice
    qué pasó no es una alerta, es una invitación a sondear."""
    _activar(db)
    u = _user(db)
    _hook(db, u)
    service.crear(db, u, sector_key=EJE, channels=["webhook"])
    _barrer(db, _evento())

    assert len(entorno) == 1
    p = entorno[0]["payload"]
    assert entorno[0]["event"] == "alert.raised"
    a = p["alert"]
    assert a["titulo"] and a["cuerpo"]
    assert a["relaciones"]["direccion"] == "por_debajo"   # la relación COMPUTADA viaja
    assert a["valores"]["cobertura"] == 91.0
    assert a["procedencia"] == {"cobertura": "live"}
    assert a["frescura"] is True
    assert a["basis"]                                     # nunca suena "porque sí"


def test_el_payload_declara_que_NO_es_un_pronostico(db, entorno):
    """Un consumidor máquina no lee la doctrina: el aviso tiene que decirlo."""
    _activar(db)
    u = _user(db)
    _hook(db, u)
    service.crear(db, u, sector_key=EJE, channels=["webhook"])
    _barrer(db, _evento())
    assert "pronóstico" in entorno[0]["payload"]["hint"]


def test_el_payload_NO_lleva_narrativa_de_reporte(db, entorno):
    """El texto del informe es el producto; no se regala por un canal lateral."""
    _activar(db)
    u = _user(db)
    _hook(db, u)
    service.crear(db, u, sector_key=EJE, channels=["webhook"])
    _barrer(db, _evento())
    assert set(entorno[0]["payload"]["alert"]) == {
        "id", "codigo", "sector_key", "subject", "periodo", "severidad", "titulo",
        "cuerpo", "basis", "relaciones", "valores", "procedencia", "frescura"}


# ── Integración con el resto del canal ───────────────────────────────────────

def test_el_webhook_sale_YA_y_el_correo_se_encola(db, entorno):
    """Asimetría deliberada: quien integra por webhook lo hace para reaccionar, no para
    leer un resumen mañana."""
    _activar(db)
    u = _user(db)
    _hook(db, u)
    import shared.notifications.email as mail
    from unittest.mock import patch

    with patch.object(mail, "configurado", lambda: True):
        service.crear(db, u, sector_key=EJE, channels=["email", "webhook"])
        _barrer(db, _evento())

    assert len(entorno) == 1                              # webhook: ya salió
    assert db.query(AlertDelivery).one().enviado_at is None  # correo: pendiente


def test_lo_VETADO_no_llega_al_webhook(db, entorno):
    """El gate es el mismo para los tres canales: una señal sin frescura establecida no se
    publica por ninguno."""
    _activar(db)
    u = _user(db)
    _hook(db, u)
    service.crear(db, u, sector_key=EJE, channels=["webhook"])
    sin_frescura = rule_umbral(
        sector_key=EJE, subject="", sujeto_label="Sistema", periodo="2026-Q2",
        metrica="cobertura", metrica_label="Cobertura", valor=91.0, umbral=100.0,
        direccion="por_debajo", severidad="alta", basis="x", frescura=None)
    res = _barrer(db, sin_frescura)

    assert res["vetadas"] == {"frescura_indeterminada": 1}
    assert entorno == []


def test_un_webhook_que_revienta_no_aborta_el_barrido(db, entorno, monkeypatch):
    _activar(db)
    u = _user(db)
    _hook(db, u)
    service.crear(db, u, sector_key=EJE, channels=["inapp", "webhook"])

    def explota(*a, **k):
        raise RuntimeError("la red del cliente")

    monkeypatch.setattr(webhook, "hooks_de", explota)
    res = entrega._despachar_webhook(db, "no-existe", str(u.id))
    assert res == 0
    assert _barrer(db, _evento())["entregadas"] == 1      # el in-app llegó igual


# ── El alta del webhook ──────────────────────────────────────────────────────

def test_el_alta_acepta_alert_raised_y_lo_distingue_del_comodin(db):
    from shared.data_api.service import register_webhook

    u = _user(db)
    db.add(ApiKey(id="k1", user_id=u.id, name="PMS", prefix="sdq_x", secret_hash="h",
                  active=True))
    db.commit()
    out = register_webhook(db, api_key_id="k1", url="https://cliente.do/hook",
                           events=webhook.EVENTO)
    assert out["events"] == webhook.EVENTO
    # Y el mensaje de error dice explícitamente que "*" NO lo incluye.
    from shared.data_api.service import ApiKeyError

    with pytest.raises(ApiKeyError) as e:
        register_webhook(db, api_key_id="k1", url="https://cliente.do/x",
                         events="evento.inventado")
    assert webhook.EVENTO in str(e.value)
    assert "NO incluye" in str(e.value)
