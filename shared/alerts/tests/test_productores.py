"""El productor transversal — y las dos formas de que alcance a NADIE sin fallar.

Las dos ya ocurrieron mientras se escribía este módulo, y las dos son silenciosas:

1. **El registro corría antes que los productos.** `registered_sectors()` devolvía la lista
   vacía, se enganchaban cero ejes y el arranque no se quejaba.
2. **El motor de validación se buscaba por la clave del eje.** `MOTORES` se indexa por
   MÓDULO (`banking_score`) y el catálogo por SECTOR (`banking`): de ocho motores, una sola
   clave coincidía por casualidad. `MOTORES.get("banking")` devolvía `None` y el eje quedaba
   mudo para siempre.

Ninguna de las dos rompe nada. Por eso están abajo.
"""
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from shared.alerts import observaciones, productores
from shared.alerts.models import AlertDelivery, AlertEventRow, AlertSubscription
from shared.auth.models import User
from shared.database.base import Base
from shared.notifications.service import Notification
from shared.settings.models import AppSetting


@pytest.fixture()
def db():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False},
                           poolclass=StaticPool)
    Base.metadata.create_all(engine, tables=[
        User.__table__, AlertSubscription.__table__, AlertEventRow.__table__,
        AlertDelivery.__table__, Notification.__table__, AppSetting.__table__])
    s = sessionmaker(bind=engine)()
    try:
        yield s
    finally:
        s.close()


# ── El registro alcanza a más de un eje ──────────────────────────────────────

def test_el_barrido_alcanza_mas_que_banca():
    """Guard del defecto nº1. Si el registro vuelve a correr antes que los `products`,
    `registered_sectors()` da vacío, se enganchan cero ejes y nadie se entera."""
    import app.main  # noqa: F401 — el arranque real, con su orden real
    from shared.alerts.motor import registered_sectors

    from shared.products.registry import registered_sectors as productos_registrados

    ejes = set(registered_sectors())
    productos = set(productos_registrados())
    assert "banking" in ejes, "banca perdió su adaptador propio"
    # Conjuntos completos, no un mínimo: la primera versión de este test pedía `> 5` y pasó
    # con 14 de 16 mientras `macro` y `monetary_policy` quedaban afuera, porque sus
    # `products` se importan DESPUÉS del resto. Un umbral flojo deja pasar el defecto que
    # el test existe para atrapar.
    assert ejes == productos, (
        f"ejes sin productor de alertas: {sorted(productos - ejes)}. Revisá que "
        f"`register()` corra después de TODOS los imports de `products` en app/main.py")


def test_banca_conserva_su_adaptador_propio():
    """El registro es UNO por eje: engancharle el transversal encima cambiaría sus señales
    calibradas (umbral/banda/brecha sobre precursores de 2003) por las genéricas."""
    import app.main  # noqa: F401
    from shared.alerts.motor import _PRODUCTORES

    assert _PRODUCTORES["banking"].__module__.endswith("banking_score.alerts_producer")


def test_cada_productor_transversal_cierra_sobre_SU_eje():
    """El clásico de las lambdas en un `for`: sin la fábrica, los N productores comparten
    la última clave del bucle y todos producen para el mismo eje."""
    import app.main  # noqa: F401
    from shared.alerts.motor import _PRODUCTORES

    nombres = {k: v.__name__ for k, v in _PRODUCTORES.items() if k != "banking"}
    assert len(set(nombres.values())) == len(nombres), (
        "hay productores que comparten identidad: la fábrica no está cerrando sobre el eje")
    for eje, nombre in nombres.items():
        assert nombre.endswith(eje), f"{eje} quedó atado a {nombre}"


# ── El puente al motor de validación ─────────────────────────────────────────

def test_el_motor_NO_se_busca_por_la_clave_del_eje():
    """Guard del defecto nº2, comprobado sobre el hecho que lo causa: las dos indexaciones
    son distintas y solo una clave coincide por casualidad."""
    import app.main  # noqa: F401
    from shared.products.registry import CATALOG_BY_KEY
    from shared.validation.frescura import MOTORES

    coincidencias = set(MOTORES) & set(CATALOG_BY_KEY)
    assert len(coincidencias) < len(MOTORES), (
        "si TODAS las claves coincidieran, este test dejaría de proteger algo — revisá si "
        "la indexación se unificó y el puente ya no hace falta")


def test_la_cobertura_encuentra_los_motores_por_el_PUENTE(db):
    """Con el puente (`ESTADO_BACKTEST.eje_motor`), banca y los demás sí aparecen."""
    import app.main  # noqa: F401

    cob = productores.cobertura(db)
    con_frescura = [eje for eje, codigos in cob.items() if "frescura" in codigos]
    assert "banking" in con_frescura
    assert len(con_frescura) >= 5, (
        f"solo {len(con_frescura)} eje(s) con frescura: el puente al motor se rompió")


def test_la_cobertura_declara_los_ejes_SIN_disparadores(db):
    """Un eje que hoy no aporta nada se lista vacío, no se omite: omitirlo lo haría
    desaparecer y el cliente no sabría que no le va a llegar nada."""
    import app.main  # noqa: F401
    from shared.products.registry import CATALOG_BY_KEY

    cob = productores.cobertura(db)
    assert set(cob) == set(CATALOG_BY_KEY)
    assert any(v == [] for v in cob.values()), (
        "ningún eje sin disparadores: ¿o todos aportan, o la cobertura está mintiendo?")


# ── Ningún productor inventa un «antes» ──────────────────────────────────────

def test_sin_observacion_previa_las_reglas_de_transicion_CALLAN(db):
    """La primera vez que se mira algo no hay noticia, hay estado. Un default (0, False, "")
    convertiría cada primera corrida en una tormenta de cambios que nunca ocurrieron."""
    assert observaciones.leer(db, "alert_obs:x:y:z") is None


def test_la_observacion_se_guarda_haya_o_no_cambio(db):
    """Si solo se guardara al disparar, un valor que va A→B→A dejaría el registro en A y el
    segundo retorno a A parecería un cambio."""
    k = observaciones.clave("esg", "", "posicion:irc")
    assert observaciones.transicion(db, k, "A") is None
    assert observaciones.transicion(db, k, "B") == "A"
    assert observaciones.transicion(db, k, "A") == "B"
    assert observaciones.leer(db, k) == "A"


def test_una_observacion_ilegible_cuenta_como_nunca_vista(db):
    """Ante la duda, callar una transición real es preferible a inventar una que no pasó."""
    k = observaciones.clave("esg", "", "rota")
    db.add(AppSetting(key=k, value="{no es json", is_secret=False))
    db.commit()
    assert observaciones.leer(db, k) is None


def test_la_observacion_soporta_los_tres_estados_de_la_frescura(db):
    """`None` tiene que sobrevivir el viaje: es el indeterminado, y si se guardara como
    «nunca visto» la transición None→True no se distinguiría de la primera corrida."""
    k = observaciones.clave("banking", "", "validacion_stale")
    observaciones.guardar(db, k, None)
    assert observaciones.leer(db, k) is None
    observaciones.guardar(db, k, False)
    assert observaciones.leer(db, k) is False
    observaciones.guardar(db, k, True)
    assert observaciones.leer(db, k) is True


# ── Aislamiento ──────────────────────────────────────────────────────────────

def test_un_disparador_que_falla_no_aborta_a_los_otros(db, monkeypatch):
    """Los tres disparadores del transversal son independientes: que la lectura de scores
    reviente no puede tapar un aviso de validación vencida."""
    def explota(*a, **k):
        raise RuntimeError("el panel no cargó")

    monkeypatch.setattr(productores, "_eventos_posicion", explota)
    prod = productores.producir(db, "esg")
    assert prod is not None
    assert isinstance(prod.eventos, list)
