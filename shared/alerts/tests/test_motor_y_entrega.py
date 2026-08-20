"""El barrido punta a punta: productor → gate → bandeja, con lo vetado registrado.

Se usa un productor de prueba en vez del de banca: lo que se verifica acá es el CICLO
(dedup, resolución, filtros, acceso, tope), no la calibración de ningún umbral. El adaptador
de banca tiene su propio test.
"""
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from shared.alerts import entrega, motor, service
from shared.alerts.models import AlertEventRow, AlertSubscription
from shared.alerts.reglas import rule_umbral
from shared.auth.models import AccessTier, User, UserRole
from shared.database.base import Base
from shared.notifications.service import Notification
from shared.products.models import ProductActivation, ProductEntitlement, Subscription
from shared.products.tiers import ProductTier
from shared.settings.models import AppSetting

EJE = "banking"
CLAVE = f"{EJE}::umbral:cobertura"      # sujeto vacío = alerta del eje entero


@pytest.fixture()
def db():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False},
                           poolclass=StaticPool)
    Base.metadata.create_all(engine, tables=[
        User.__table__, AlertSubscription.__table__, AlertEventRow.__table__,
        Notification.__table__, AppSetting.__table__, ProductActivation.__table__,
        ProductEntitlement.__table__, Subscription.__table__])
    s = sessionmaker(bind=engine)()
    try:
        yield s
    finally:
        s.close()


@pytest.fixture(autouse=True)
def sin_productores():
    """El registro de productores es global (se puebla al importar los módulos). Se aísla
    para que un test no herede el productor real de banca."""
    previos = dict(motor._PRODUCTORES)
    motor._PRODUCTORES.clear()
    yield
    motor._PRODUCTORES.clear()
    motor._PRODUCTORES.update(previos)


class _Producto:
    """Doble del producto de banca: sujeto FIJO (no implementa ``scope_options``), que es
    lo que estos tests necesitan — las alertas son del eje entero."""


@pytest.fixture(autouse=True)
def producto(monkeypatch):
    monkeypatch.setattr(service, "get_product", lambda key, db=None:
                        _Producto() if key == EJE else None)


def _user(db, uid="u1", tier=AccessTier.free):
    u = User(id=uid, email=f"{uid}@sdq.do", password_hash="x", full_name="T",
             role=UserRole.viewer, tier=tier, is_active=True)
    db.add(u)
    db.commit()
    return u


def _activar(db, *tiers):
    for t in tiers:
        db.add(ProductActivation(sector_key=EJE, tier=t.value, is_active=True))
    db.commit()


def _evento(valor=91.0, frescura=True, severidad="alta"):
    return rule_umbral(
        sector_key=EJE, subject="", sujeto_label="Sistema", periodo="2026-Q2",
        metrica="cobertura", metrica_label="Cobertura de provisiones", valor=valor,
        umbral=100.0, direccion="por_debajo", severidad=severidad,
        basis="crisis RD 2003", frescura=frescura)


def _productor(eventos, evaluadas=None):
    prod = motor.Produccion(eventos=list(eventos),
                            evaluadas=set(evaluadas if evaluadas is not None else [CLAVE]))
    return lambda db: prod


def _vigilar(db, user, **kw):
    return service.crear(db, user, sector_key=EJE, **kw)


# ── El ciclo completo ────────────────────────────────────────────────────────

def test_del_productor_a_la_bandeja(db):
    _activar(db, ProductTier.pulse)
    u = _user(db)
    _vigilar(db, u)
    motor.register_producer(EJE, _productor([_evento()]))

    res = motor.run_alerts_sweep(db)

    assert res["publicadas"] == 1 and res["entregadas"] == 1
    n = db.query(Notification).one()
    assert "Cobertura de provisiones" in n.title
    assert "por debajo del umbral" in n.body
    assert "Señal a monitorear" in n.body      # la alerta dice de dónde sale su umbral
    fila = db.query(AlertEventRow).one()
    assert bool(fila.publicada) is True and fila.entregas == 1


def test_sin_vigilancias_el_evento_se_registra_pero_no_entrega(db):
    """``publicada=True`` con ``entregas=0`` es un dato, no un error: el gate lo dejó pasar
    y nadie lo estaba vigilando."""
    motor.register_producer(EJE, _productor([_evento()]))
    res = motor.run_alerts_sweep(db)
    assert res["publicadas"] == 1 and res["entregadas"] == 0
    assert db.query(AlertEventRow).one().entregas == 0
    assert db.query(Notification).count() == 0


# ── Lo vetado se LISTA, no desaparece ────────────────────────────────────────

def test_lo_vetado_se_persiste_con_su_motivo_y_no_entrega(db):
    _activar(db, ProductTier.pulse)
    u = _user(db)
    _vigilar(db, u)
    motor.register_producer(EJE, _productor([_evento(frescura=None)]))

    res = motor.run_alerts_sweep(db)

    assert res["publicadas"] == 0 and res["entregadas"] == 0
    assert res["vetadas"] == {"frescura_indeterminada": 1}
    fila = db.query(AlertEventRow).one()
    assert bool(fila.publicada) is False
    assert fila.veto_motivo == "frescura_indeterminada"
    assert fila.veto_detalle                   # el motivo legible viaja con la fila
    assert db.query(Notification).count() == 0


def test_el_historial_del_usuario_resume_las_vetadas(db):
    """«No recibí nada» y «hay una señal retenida porque el dato no está vigente» son cosas
    distintas, y solo la segunda es accionable."""
    _activar(db, ProductTier.pulse)
    u = _user(db)
    _vigilar(db, u)
    motor.register_producer(EJE, _productor([_evento(frescura=False)]))
    motor.run_alerts_sweep(db)

    hist = service.eventos_para(db, u.id)
    assert hist["total"] == 1
    assert hist["vetadas"] == {"frescura_vencida": 1}
    assert hist["events"][0]["publicada"] is False


def test_el_historial_no_muestra_ejes_que_el_usuario_no_vigila(db):
    _activar(db, ProductTier.pulse)
    u = _user(db)
    motor.register_producer(EJE, _productor([_evento()]))
    motor.run_alerts_sweep(db)
    hist = service.eventos_para(db, u.id)
    assert hist["sin_vigilancias"] is True and hist["events"] == []


# ── Dedup: callar mientras siga roto, reabrir si recae ───────────────────────

def test_no_re_avisa_la_misma_condicion_en_el_barrido_siguiente(db):
    _activar(db, ProductTier.pulse)
    u = _user(db)
    _vigilar(db, u)
    motor.register_producer(EJE, _productor([_evento()]))

    motor.run_alerts_sweep(db)
    segundo = motor.run_alerts_sweep(db)

    assert segundo["entregadas"] == 0
    assert db.query(Notification).count() == 1     # una sola, no dos
    assert db.query(AlertEventRow).count() == 2    # el hecho se registra igual


def test_si_la_condicion_se_RESUELVE_y_recae_vuelve_a_avisar(db):
    """La mitad que se olvida del dedup. Sin ella, la señal más valiosa —algo que se arregló
    y volvió a romperse— sería justo la que no se avisa."""
    _activar(db, ProductTier.pulse)
    u = _user(db)
    _vigilar(db, u)

    motor.register_producer(EJE, _productor([_evento()]))
    motor.run_alerts_sweep(db)
    assert db.query(Notification).count() == 1

    # Barrido con la condición evaluada y SIN disparar → se resuelve el marcador.
    motor.register_producer(EJE, _productor([], evaluadas=[CLAVE]))
    motor.run_alerts_sweep(db)

    # Recae: tiene que volver a avisar aunque no venció ningún intervalo.
    motor.register_producer(EJE, _productor([_evento()]))
    motor.run_alerts_sweep(db)
    assert db.query(Notification).count() == 2


def test_una_condicion_que_nadie_pudo_EVALUAR_no_se_da_por_resuelta(db):
    """Sin dato no es lo mismo que estar bien. Si un barrido sin el insumo limpiara el
    marcador, el aviso se repetiría en cuanto el dato volviera — y ese repique diría
    «pasó algo» cuando lo único que pasó es que se pudo mirar de nuevo."""
    _activar(db, ProductTier.pulse)
    u = _user(db)
    _vigilar(db, u)
    motor.register_producer(EJE, _productor([_evento()]))
    motor.run_alerts_sweep(db)

    # El productor no pudo evaluar nada: `evaluadas` vacío, no "todo resuelto".
    motor.register_producer(EJE, _productor([], evaluadas=[]))
    motor.run_alerts_sweep(db)

    motor.register_producer(EJE, _productor([_evento()]))
    motor.run_alerts_sweep(db)
    assert db.query(Notification).count() == 1     # sigue callada: nunca se resolvió


# ── Filtros de la vigilancia ─────────────────────────────────────────────────

def test_la_severidad_minima_filtra(db):
    _activar(db, ProductTier.pulse)
    u = _user(db)
    _vigilar(db, u, min_severity="alta")
    motor.register_producer(EJE, _productor([_evento(severidad="baja")]))
    res = motor.run_alerts_sweep(db)
    assert res["publicadas"] == 1 and res["entregadas"] == 0


def test_los_disparadores_elegidos_filtran(db):
    _activar(db, ProductTier.pulse)
    u = _user(db)
    _vigilar(db, u, rule_codes=["banda"])
    motor.register_producer(EJE, _productor([_evento()]))       # código "umbral"
    assert motor.run_alerts_sweep(db)["entregadas"] == 0


def test_el_tope_por_barrido_no_trunca_en_silencio(db):
    """El excedente se REPORTA. Un corte callado se lee como que no pasó nada más."""
    _activar(db, ProductTier.pulse)
    u = _user(db)
    _vigilar(db, u)
    eventos = [
        rule_umbral(sector_key=EJE, subject="", sujeto_label="Sistema", periodo="2026-Q2",
                    metrica=f"m{i}", metrica_label=f"Métrica {i}", valor=1.0, umbral=9.0,
                    direccion="por_debajo", severidad="alta", basis="b", frescura=True)
        for i in range(entrega.MAX_POR_USUARIO_POR_BARRIDO + 3)]
    motor.register_producer(EJE, _productor(eventos, evaluadas=[]))

    res = motor.run_alerts_sweep(db)
    assert res["entregadas"] == entrega.MAX_POR_USUARIO_POR_BARRIDO
    assert db.query(Notification).count() == entrega.MAX_POR_USUARIO_POR_BARRIDO
    # Y las que no entraron quedaron registradas como hechos publicados igual.
    assert db.query(AlertEventRow).filter(AlertEventRow.publicada.is_(True)).count() == len(eventos)


# ── Acceso: se re-verifica en la ENTREGA ─────────────────────────────────────

def test_una_vigilancia_sin_acceso_vigente_no_recibe(db):
    """La vigilancia sobrevive al fin del contrato; la entrega no puede."""
    _activar(db, ProductTier.pulse, ProductTier.insight)
    u = _user(db, tier=AccessTier.pro)
    service.crear(db, u, sector_key=EJE, subject=None)
    sub = db.query(AlertSubscription).one()
    sub.sector_key = EJE
    db.commit()

    # Se le quita el producto entero: ni Pulse queda publicado.
    for a in db.query(ProductActivation).all():
        a.is_active = False
    db.commit()

    motor.register_producer(EJE, _productor([_evento()]))
    res = motor.run_alerts_sweep(db)
    assert res["entregadas"] == 0
    db.refresh(sub)
    assert sub.suspended_reason == "acceso_revocado"


# ── Aislamiento entre ejes ───────────────────────────────────────────────────

def test_un_productor_que_falla_no_aborta_a_los_demas(db):
    _activar(db, ProductTier.pulse)
    u = _user(db)
    _vigilar(db, u)

    def explota(db):
        raise RuntimeError("el panel no cargó")

    motor.register_producer("macro", explota)
    motor.register_producer(EJE, _productor([_evento()]))

    res = motor.run_alerts_sweep(db)
    assert res["entregadas"] == 1
    assert "macro" not in res["por_eje"]
