"""El canal de correo: la cola, la cadencia y las tres formas de NO mandar.

Lo que más importa acá no es que el correo salga, sino que **no salga cuando no corresponde**:
sin SMTP configurado, sin acceso vigente, o antes de que venza la cadencia elegida. Un correo
de más a un cliente que dejó de pagar es peor que un correo de menos.
"""
import datetime as _dt

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from shared.alerts import digest, entrega, motor, service
from shared.alerts.models import (AlertDelivery, AlertEventRow, AlertSubscription)
from shared.alerts.reglas import rule_umbral
from shared.auth.models import AccessTier, User, UserRole
from shared.database.base import Base
from shared.notifications import email as mail
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
        ProductActivation.__table__, ProductEntitlement.__table__, Subscription.__table__])
    s = sessionmaker(bind=engine)()
    try:
        yield s
    finally:
        s.close()


class _Producto:
    """Eje de sujeto FIJO: las alertas de estos tests son del eje entero."""


@pytest.fixture(autouse=True)
def entorno(monkeypatch):
    """SMTP configurado y correo capturado en memoria — ningún test manda nada de verdad."""
    monkeypatch.setattr(service, "get_product",
                        lambda key, db=None: _Producto() if key == EJE else None)
    monkeypatch.setattr(mail, "configurado", lambda: True)
    enviados = []
    monkeypatch.setattr(mail, "enviar",
                        lambda to, asunto, texto, html=None: (
                            enviados.append({"to": to, "asunto": asunto, "texto": texto})
                            or True))
    previos = dict(motor._PRODUCTORES)
    motor._PRODUCTORES.clear()
    yield enviados
    motor._PRODUCTORES.clear()
    motor._PRODUCTORES.update(previos)


def _user(db, uid="u1", tier=AccessTier.free):
    u = User(id=uid, email=f"{uid}@sdq.do", password_hash="x", full_name="T",
             role=UserRole.viewer, tier=tier, is_active=True)
    db.add(u)
    db.commit()
    return u


def _activar(db):
    db.add(ProductActivation(sector_key=EJE, tier=ProductTier.pulse.value, is_active=True))
    db.commit()


def _evento(metrica="cobertura"):
    return rule_umbral(
        sector_key=EJE, subject="", sujeto_label="Sistema", periodo="2026-Q2",
        metrica=metrica, metrica_label="Cobertura de provisiones", valor=91.0,
        umbral=100.0, direccion="por_debajo", severidad="alta",
        basis="crisis RD 2003", frescura=True)


def _barrer(db, *eventos):
    motor.register_producer(EJE, lambda _db: motor.Produccion(
        eventos=list(eventos), evaluadas=set()))
    return motor.run_alerts_sweep(db)


def _vigilar(db, u, **kw):
    kw.setdefault("channels", ["inapp", "email"])
    return service.crear(db, u, sector_key=EJE, **kw)


# ── La cola ──────────────────────────────────────────────────────────────────

def test_el_barrido_ENCOLA_el_correo_pero_no_lo_manda(db, entorno):
    """Una conexión SMTP dentro del barrido lo vuelve tan lento como el servidor de correo,
    y un SMTP caído se comería el aviso sin dejar rastro."""
    _activar(db)
    _vigilar(db, _user(db))
    _barrer(db, _evento())

    assert entorno == []                                  # no salió nada todavía
    fila = db.query(AlertDelivery).one()
    assert fila.canal == "email" and fila.enviado_at is None
    assert db.query(Notification).count() == 1            # el buzón in-app sí, al toque


def test_el_digest_manda_lo_pendiente_y_lo_marca(db, entorno):
    _activar(db)
    _vigilar(db, _user(db))
    _barrer(db, _evento())

    res = digest.enviar_digests(db)

    assert res["enviados"] == 1 and res["usuarios"] == 1
    assert len(entorno) == 1
    assert "Cobertura de provisiones" in entorno[0]["asunto"]
    assert "por debajo del umbral" in entorno[0]["texto"]
    assert "Señal a monitorear" in entorno[0]["texto"]     # el correo dice de dónde sale
    assert db.query(AlertDelivery).one().enviado_at is not None


def test_no_manda_dos_veces_lo_mismo(db, entorno):
    _activar(db)
    _vigilar(db, _user(db))
    _barrer(db, _evento())
    digest.enviar_digests(db)
    digest.enviar_digests(db)
    assert len(entorno) == 1


def test_varias_senales_van_en_UN_correo(db, entorno):
    """Tres señales del mismo trimestre son tres correos que el cliente archiva sin leer."""
    _activar(db)
    _vigilar(db, _user(db))
    _barrer(db, _evento("cobertura"), _evento("solvencia"), _evento("morosidad"))

    res = digest.enviar_digests(db)
    assert res["usuarios"] == 1 and res["enviados"] == 3
    assert len(entorno) == 1
    assert "3 señales" in entorno[0]["asunto"]


def test_el_correo_lleva_como_darse_de_baja(db, entorno):
    """Un correo sin salida es un correo que se marca como spam."""
    _activar(db)
    _vigilar(db, _user(db))
    _barrer(db, _evento())
    digest.enviar_digests(db)
    assert "vigilancias" in entorno[0]["texto"].lower()


# ── Las tres formas de NO mandar ─────────────────────────────────────────────

def test_SIN_SMTP_no_manda_y_lo_DECLARA(db, entorno, monkeypatch):
    """No es un error: es un despliegue sin correo. Se declara para que la consola pueda
    decir por qué la cola no baja, en vez de mostrar cero y punto."""
    _activar(db)
    _vigilar(db, _user(db))
    _barrer(db, _evento())
    monkeypatch.setattr(mail, "configurado", lambda: False)

    res = digest.enviar_digests(db)
    assert res["enviados"] == 0
    assert res["pendientes"] == 1
    assert res["smtp"]["falta"]                            # dice QUÉ falta
    assert entorno == []


def test_sin_acceso_vigente_no_sale_el_correo(db, entorno):
    """Entre el barrido y el envío pueden pasar días. Si el contrato venció en el medio, el
    correo saldría con dato que ya no le corresponde."""
    _activar(db)
    u = _user(db)
    _vigilar(db, u)
    _barrer(db, _evento())

    for a in db.query(ProductActivation).all():
        a.is_active = False
    db.commit()

    res = digest.enviar_digests(db)
    assert entorno == []
    assert res["sin_acceso"] == 1
    fila = db.query(AlertDelivery).one()
    # Se cierra con su motivo en vez de quedar pendiente para siempre.
    assert fila.enviado_at is not None and fila.ultimo_error == "sin_acceso_al_enviar"


def test_el_SEMANAL_espera_su_semana(db, entorno):
    _activar(db)
    u = _user(db)
    _vigilar(db, u, digest="semanal")
    _barrer(db, _evento("cobertura"))
    assert digest.enviar_digests(db)["enviados"] == 1      # el primero sale

    _barrer(db, _evento("solvencia"))
    res = digest.enviar_digests(db)
    assert res["enviados"] == 0 and res["diferidos"] == 1
    assert len(entorno) == 1


def test_el_DIARIO_no_espera(db, entorno):
    _activar(db)
    u = _user(db)
    _vigilar(db, u, digest="diario")
    _barrer(db, _evento("cobertura"))
    digest.enviar_digests(db)
    _barrer(db, _evento("solvencia"))
    assert digest.enviar_digests(db)["enviados"] == 1
    assert len(entorno) == 2


def test_una_senal_inmediata_no_espera_al_semanal(db, entorno):
    """Si el cliente mezcla cadencias, manda la más frecuente de lo pendiente: acumular una
    señal inmediata hasta el domingo sería peor que mandar el resumen antes."""
    _activar(db)
    u = _user(db)
    sub = _vigilar(db, u, digest="semanal")
    _barrer(db, _evento("cobertura"))
    digest.enviar_digests(db)                              # consume la ventana semanal

    sub.digest = "inmediato"
    db.commit()
    _barrer(db, _evento("solvencia"))
    assert digest.enviar_digests(db)["enviados"] == 1


# ── Reintento ────────────────────────────────────────────────────────────────

def test_un_envio_fallido_queda_PENDIENTE_con_su_motivo(db, entorno, monkeypatch):
    _activar(db)
    _vigilar(db, _user(db))
    _barrer(db, _evento())
    monkeypatch.setattr(mail, "enviar", lambda *a, **k: False)

    res = digest.enviar_digests(db)
    assert res["fallidos"] == 1 and res["enviados"] == 0
    fila = db.query(AlertDelivery).one()
    assert fila.enviado_at is None and fila.intentos == 1
    assert fila.ultimo_error == "envio_fallido"


def test_se_reintenta_en_la_corrida_siguiente(db, entorno, monkeypatch):
    _activar(db)
    _vigilar(db, _user(db))
    _barrer(db, _evento())
    monkeypatch.setattr(mail, "enviar", lambda *a, **k: False)
    digest.enviar_digests(db)

    monkeypatch.setattr(mail, "enviar",
                        lambda to, asunto, texto, html=None: (
                            entorno.append({"to": to, "asunto": asunto, "texto": texto})
                            or True))
    assert digest.enviar_digests(db)["enviados"] == 1
    assert db.query(AlertDelivery).one().enviado_at is not None


def test_deja_de_reintentar_pero_NO_borra_la_fila(db, entorno, monkeypatch):
    """Un destino que rebota siempre no se reintenta eterno; la fila queda con su error para
    que se pueda ver por qué ese cliente no recibe nada. Un descarte silencioso se lee como
    «no pasó nada»."""
    _activar(db)
    _vigilar(db, _user(db))
    _barrer(db, _evento())
    monkeypatch.setattr(mail, "enviar", lambda *a, **k: False)
    for _ in range(digest.MAX_INTENTOS + 2):
        digest.enviar_digests(db)

    fila = db.query(AlertDelivery).one()
    assert fila.intentos == digest.MAX_INTENTOS
    assert fila.enviado_at is None and fila.ultimo_error == "envio_fallido"


# ── Solo in-app ──────────────────────────────────────────────────────────────

def test_una_vigilancia_solo_in_app_no_encola_correo(db, entorno):
    _activar(db)
    _vigilar(db, _user(db), channels=["inapp"])
    _barrer(db, _evento())
    assert db.query(AlertDelivery).count() == 0
    assert db.query(Notification).count() == 1


def test_una_vigilancia_solo_email_no_llena_el_buzon(db, entorno):
    _activar(db)
    _vigilar(db, _user(db), channels=["email"])
    _barrer(db, _evento())
    assert db.query(Notification).count() == 0
    assert db.query(AlertDelivery).count() == 1


# ── Encolado y tope ─────────────────────────────────────────────────────────

def test_el_encolado_es_idempotente(db, entorno):
    """Dos barridos sobre el mismo evento no pueden generar dos correos."""
    _activar(db)
    u = _user(db)
    _vigilar(db, u)
    _barrer(db, _evento())
    fila = db.query(AlertEventRow).first()
    entrega._encolar_email(db, str(fila.id), str(u.id), "inmediato")
    entrega._encolar_email(db, str(fila.id), str(u.id), "inmediato")
    assert db.query(AlertDelivery).count() == 1


def test_el_tope_del_correo_resume_el_excedente(db, entorno, monkeypatch):
    """El corte se DICE. Un correo truncado en silencio se lee como que eso fue todo.

    Se levanta el tope del BARRIDO: es más chico que el del correo, así que sin esto el
    excedente nunca se produce y el test pasaría sin ejercitar nada."""
    monkeypatch.setattr(entrega, "MAX_POR_USUARIO_POR_BARRIDO", 1000)
    _activar(db)
    _vigilar(db, _user(db))
    eventos = [_evento(f"m{i}") for i in range(digest.MAX_EN_CORREO + 4)]
    motor.register_producer(EJE, lambda _db: motor.Produccion(eventos=eventos,
                                                              evaluadas=set()))
    motor.run_alerts_sweep(db)
    digest.enviar_digests(db)
    texto = entorno[0]["texto"]
    assert "señales más en la plataforma" in texto


def test_ahora_es_naive(db):
    """Las columnas DateTime son naive (parity SQLite↔Postgres); un aware rompe el insert."""
    assert digest._ahora().tzinfo is None
    assert isinstance(digest._ahora(), _dt.datetime)
