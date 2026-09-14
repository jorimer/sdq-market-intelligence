"""El sensor de fuente CONGELADA por eje: el caso positivo, el control negativo, y el
motivo por el que hacía falta un instrumento nuevo.

**La trampa que estos tests existen para cerrar.** Un verde sobre datos frescos no prueba
que un sensor detecte lo congelado. El caso positivo de acá está calcado de una fuente real
y muerta —la sección de estadísticas de la SIE, cuyo propio slug del portal declara la
serie terminada (``historico-potencia-instalada-1998-2024``, ``reporte-protecom-julio-2023``)—
y el control negativo usa **la misma función de medición**, porque dos implementaciones del
mismo criterio es exactamente cómo se cuela un falso.
"""
from datetime import date, datetime, timedelta, timezone

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from shared.database.base import Base
from shared.operations.fuentes_congeladas import (
    AL_DIA,
    CONGELADA,
    INDETERMINADA,
    TOPES_POR_CADENCIA,
    evaluar_fuente,
    leer_fuentes_de_los_ejes,
    resumen_de_fuentes,
)

#: Antigüedad del dato del eje de energía si su última anualidad completa es 2023 — la
#: forma exacta de la fuente congelada de la SIE, medida como la mide el producto
#: (``date.today() - date(period, 12, 31)``).
_DIAS_SI_EL_DATO_MUERE_EN = lambda anio: (date.today() - date(anio, 12, 31)).days  # noqa: E731


# ── Caso POSITIVO: la fuente congelada conocida ──────────────────────────────────

def test_una_fuente_anual_detenida_en_2023_se_marca_CONGELADA():
    """El caso que motiva el sensor: dato de la SIE que no avanza y un sync que corre en verde."""
    v = evaluar_fuente(eje="energy", freshness_days=_DIAS_SI_EL_DATO_MUERE_EN(2023),
                       cadence="annual", fuentes=("SIE (capacidad)", "SIE (reclamaciones)"))
    assert v.estado == CONGELADA, v.motivo
    # El sujeto viaja con el número: sin el emisor, «energía está congelada» no es accionable.
    assert "SIE (capacidad)" in v.fuentes
    assert v.dias_desde_el_periodo_del_dato > v.tope_de_dias_de_la_cadencia


@pytest.mark.parametrize("dias", [546, 600, 700, 730])
def test_hay_una_BANDA_donde_el_gate_da_frescura_PLENA_y_el_sensor_marca(dias):
    """Por qué hacía falta un instrumento nuevo y no bastaba con mirar G1.

    Entre el tope del sensor (545 d) y el umbral «fresco» de la curva anual del readiness
    (730 d) hay medio año entero en el que el gate puntúa frescura **1.0** —dato impecable,
    sin una marca— sobre una fuente que lleva año y medio sin publicar. Ahí es donde una
    fuente muerta aparenta estar viva.

    Si este test empieza a fallar es porque los umbrales del gate se estrecharon; habría que
    decidir entonces si el sensor sigue aportando.
    """
    from shared.products.readiness import _freshness_factor

    assert _freshness_factor(dias, "annual") == 1.0, (
        "el gate ya no pinta de verde este dato: revisar si el sensor sigue aportando")
    assert evaluar_fuente(eje="energy", freshness_days=dias,
                          cadence="annual").estado == CONGELADA


def test_el_gate_NO_declara_obsoleta_la_fuente_real_de_la_SIE():
    """Y pasada esa banda tampoco hay alerta: solo un descuento gradual que nadie nombra.

    Con el dato de la SIE detenido en 2023 el gate no lo da por obsoleto —le faltan años
    para eso, ``annual`` obsoletiza a los 2.190 días— así que el eje conserva su readiness y
    sigue publicando. El descuento va enterrado dentro de un score ponderado; no hay ninguna
    superficie que diga «esta fuente dejó de publicar». Eso es lo que agrega el sensor: un
    veredicto con nombre, no un ajuste silencioso.
    """
    from shared.products.readiness import _CADENCE_THRESHOLDS, _freshness_factor

    dias = _DIAS_SI_EL_DATO_MUERE_EN(2023)
    _, obsoleto = _CADENCE_THRESHOLDS["annual"]
    assert dias < obsoleto, "la SIE ya cruzó el umbral de obsolescencia del gate"
    assert _freshness_factor(dias, "annual") > 0.0, "el gate seguiría publicando este eje"
    assert evaluar_fuente(eje="energy", freshness_days=dias,
                          cadence="annual").estado == CONGELADA


# ── Control NEGATIVO: una fuente al día NO se marca ──────────────────────────────

@pytest.mark.parametrize("cadencia,dias", [
    ("annual", 252),      # cifra anual del año pasado, publicada con rezago normal
    ("quarterly", 95),    # trimestre cerrado, publicado el mes siguiente
    ("monthly", 35),      # mes cerrado
])
def test_una_fuente_al_dia_NO_se_marca(cadencia, dias):
    """Mismo criterio, misma función: un eje con fuente viva pasa en `al_dia`."""
    v = evaluar_fuente(eje="banking", freshness_days=dias, cadence=cadencia,
                       fuentes=("SIB",))
    assert v.estado == AL_DIA, v.motivo


def test_el_tope_es_inclusivo_y_el_dia_siguiente_marca():
    """El borde exacto, para que el umbral sea un hecho y no una impresión."""
    tope = TOPES_POR_CADENCIA["quarterly"]
    assert evaluar_fuente(eje="x", freshness_days=tope, cadence="quarterly").estado == AL_DIA
    assert evaluar_fuente(eje="x", freshness_days=tope + 1,
                          cadence="quarterly").estado == CONGELADA


# ── El tercer estado: «no sé» NO es «está al día» ────────────────────────────────

@pytest.mark.parametrize("freshness,cadencia", [
    (None, "annual"),        # el producto no declara la antigüedad de su dato
    (100, "unknown"),        # cadencia sin tope definido
    (100, ""),               # cadencia sin declarar
    (-5, "annual"),          # período en el futuro: la medición no es interpretable
])
def test_lo_que_no_se_puede_medir_queda_INDETERMINADO_y_nunca_al_dia(freshness, cadencia):
    """Confundir «no sé de cuándo es» con «está al día» dejó un número viejo publicado
    diecinueve días. Lo indeterminado se lista; no se pinta de verde."""
    v = evaluar_fuente(eje="x", freshness_days=freshness, cadence=cadencia)
    assert v.estado == INDETERMINADA
    assert v.estado != AL_DIA
    assert v.motivo, "un indeterminado sin motivo escrito no es accionable"


def test_una_cadencia_desconocida_NO_hereda_el_tope_de_otra():
    """Aplicarle el tope trimestral a una cadencia que no declaramos sería inventar el
    criterio: el veredicto saldría con cara de medición."""
    v = evaluar_fuente(eje="x", freshness_days=10_000, cadence="cada-luna-llena")
    assert v.estado == INDETERMINADA
    assert v.tope_de_dias_de_la_cadencia is None


# ── El barrido completo, contra el catálogo real ─────────────────────────────────

@pytest.fixture()
def db():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False},
                           poolclass=StaticPool)
    Base.metadata.create_all(engine)
    s = sessionmaker(bind=engine)()
    try:
        yield s
    finally:
        s.close()


def test_el_barrido_ENCUENTRA_ejes(db):
    """Un barrido vacío pasaría en verde sin comprobar nada, y todo lo de arriba con él."""
    veredictos = leer_fuentes_de_los_ejes(db)
    assert len(veredictos) >= 10, f"el catálogo se quedó ciego: {len(veredictos)} ejes"
    assert {v.eje for v in veredictos} >= {"energy", "construction", "banking"}


def test_el_resumen_separa_las_dos_listas_que_se_miran_primero(db):
    r = resumen_de_fuentes(db)
    assert set(r) >= {"ejes", "congeladas", "indeterminadas", "topes_por_cadencia"}
    # Sin dato persistido ningún eje puede declarar antigüedad: todos indeterminados, y
    # ninguno se cuela como «al día».
    assert r["indeterminadas"], "un eje sin dato no puede salir al día"
    estados = {e["estado"] for e in r["ejes"]}
    assert AL_DIA not in estados or r["congeladas"] is not None


# ── De punta a punta por el producto REAL, con dato sembrado ─────────────────────

def _sembrar_irse(db, periodo: str) -> None:
    from modules.energy_intel.models.models import EnergyScore

    db.add(EnergyScore(period=periodo, energy_score=61.0, band="B", coverage=1.0,
                       capacity_mw=5000.0, capacity_score=60.0, service_score=62.0,
                       transition_score=61.0, breakdown={}))
    db.commit()


def test_de_punta_a_punta_el_eje_de_energia_con_su_fuente_MUERTA_se_marca(db):
    """El sensor leyendo el producto real, no una señal inventada: última anualidad 2023."""
    _sembrar_irse(db, "2023")
    v = next(x for x in leer_fuentes_de_los_ejes(db) if x.eje == "energy")
    assert v.estado == CONGELADA, v.motivo
    assert "SIE" in " ".join(v.fuentes)


def test_de_punta_a_punta_el_mismo_eje_con_su_fuente_VIVA_no_se_marca(db):
    """Control negativo por el mismo camino: cambia el dato, no el criterio."""
    _sembrar_irse(db, str(date.today().year - 1))
    v = next(x for x in leer_fuentes_de_los_ejes(db) if x.eje == "energy")
    assert v.estado == AL_DIA, v.motivo


# ── El aviso: llega, y no se repite a diario ─────────────────────────────────────

def test_la_auditoria_avisa_la_fuente_congelada_una_sola_vez(db):
    from shared.auth.models import User, UserRole
    from shared.notifications.service import Notification
    from shared.operations.fuentes_congeladas import auditar_fuentes_de_los_ejes

    u = User(email="a@b.do", password_hash="x", full_name="A",
             role=UserRole.admin, is_active=True)
    db.add(u)
    db.commit()
    _sembrar_irse(db, "2023")
    ahora = datetime.now(timezone.utc).replace(tzinfo=None)

    avisados = auditar_fuentes_de_los_ejes(db, [u.id], ahora)
    assert "energy" in avisados
    cuerpo = db.query(Notification).filter(Notification.user_id == u.id).all()
    assert any("energy" in (n.title or "") for n in cuerpo)
    # El emisor y las dos cifras del veredicto viajan en el aviso.
    aviso = next(n for n in cuerpo if "energy" in (n.title or ""))
    assert "SIE" in (aviso.body or "") and "annual" in (aviso.body or "")

    # Segundo día: mismo estado → no se re-avisa (anti-spam).
    assert auditar_fuentes_de_los_ejes(db, [u.id], ahora + timedelta(days=1)) == []


# ── Por HTTP: la superficie del operador, no solo el motor ───────────────────────
# Van cinco defectos en este repo que vivían en la ruta con los tests del motor en verde.
# Un sensor que detecta y cuyo hallazgo no llega a ninguna pantalla es trabajo perdido.

class _Admin:
    id = "admin-1"
    role = None          # se rellena abajo (evita importar UserRole en el encabezado)
    organization_id = None
    email = "admin@sdq.test"


def _cliente(db):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from shared.auth.dependencies import get_current_user
    from shared.auth.models import UserRole
    from shared.database.session import get_db
    from shared.operations.router import router

    _Admin.role = UserRole.admin
    app = FastAPI()
    app.include_router(router, prefix="/api/v1/operations")
    app.dependency_overrides[get_db] = lambda: db
    app.dependency_overrides[get_current_user] = lambda: _Admin()
    return TestClient(app)


def test_por_HTTP_el_operador_VE_la_fuente_congelada(db):
    _sembrar_irse(db, "2023")
    r = _cliente(db).get("/api/v1/operations/fuentes")
    assert r.status_code == 200, r.text
    cuerpo = r.json()
    assert "energy" in cuerpo["congeladas"]
    fila = next(e for e in cuerpo["ejes"] if e["eje"] == "energy")
    assert fila["estado"] == CONGELADA
    # Lo que el operador necesita para actuar: el emisor, la edad y contra qué se juzga.
    assert fila["fuentes"] and "SIE" in " ".join(fila["fuentes"])
    assert fila["dias_desde_el_periodo_del_dato"] > fila["tope_de_dias_de_la_cadencia"]


def test_por_HTTP_lo_indeterminado_se_LISTA_aparte(db):
    """Un veto silencioso se lee como que el eje no tiene problema."""
    cuerpo = _cliente(db).get("/api/v1/operations/fuentes").json()
    assert cuerpo["indeterminadas"], "los ejes sin dato desaparecieron de la respuesta"
    # La lista va por `id` (eje:fuente), como dice `resumen_de_fuentes`: un eje puede tener su
    # índice al día y un feed indeterminado. Comparar contra los ejes solo pasaba mientras ningún
    # FEED quedaba indeterminado; con JurisAI sin credencial, `law:jurisai` lo es.
    listados = {e["id"] for e in cuerpo["ejes"]}
    assert set(cuerpo["indeterminadas"]) <= listados


def test_por_HTTP_el_panel_es_de_ADMIN(db):
    from shared.auth.models import UserRole

    cliente = _cliente(db)
    _Admin.role = UserRole.viewer
    assert cliente.get("/api/v1/operations/fuentes").status_code == 403


# ── El límite de lo que el sensor puede afirmar ──────────────────────────────────

def test_un_eje_de_INSTRUMENTO_no_se_declara_congelado(db):
    """`law` tiene la cifra y la cifra no mide esto.

    Su `freshness_days` es la antigüedad del indicador MÁS VIEJO entre decenas —así lo
    declara a propósito— y su `sources` es la norma evaluada, que no publica ediciones.
    Aplicarle el sensor produciría «la fuente Ley 1-12 END 2030 debió publicar una edición
    nueva a los 545 días», que es literalmente falso. Se declara indeterminado, con motivo,
    y se LISTA — no desaparece del panel.
    """
    v = next(x for x in leer_fuentes_de_los_ejes(db) if x.eje == "law")
    assert v.estado == INDETERMINADA, v.motivo
    assert "INSTRUMENTO" in v.motivo and "no mide esto" in v.motivo
    assert "law" in resumen_de_fuentes(db)["indeterminadas"]


def test_la_exclusion_va_por_la_SEMANTICA_declarada_y_no_por_el_nombre_del_eje(db):
    """Una lista de nombres se pudre: el eje de instrumento que entre mañana quedaría dentro
    del sensor sin que nadie se acuerde de esta línea."""
    import inspect

    from shared.operations import fuentes_congeladas as mod

    fuente = inspect.getsource(mod)
    assert "COVERAGE_INSTRUMENT" in fuente
    assert '"law"' not in fuente and "'law'" not in fuente, (
        "la exclusión se cableó al nombre del eje en vez de a su semántica declarada")
