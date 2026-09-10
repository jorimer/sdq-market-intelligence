"""El contador de corridas de las herramientas comerciales.

**Y se prueba POR HTTP, no solo el motor.** En este repo van cinco defectos que vivían en la
ruta mientras los tests del motor seguían verdes. Un contador que funciona perfecto y que
nadie llama desde el endpoint no cuenta nada, y el síntoma —un panel en cero— se lee como
«no la usó nadie», que es una respuesta comercialmente opuesta.
"""
from datetime import date, datetime, time, timezone

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from shared.auth.models import UserRole
from shared.database.base import Base
from shared.database.session import get_db
from shared.observability.models import ToolRun
from shared.observability.uso_de_herramientas import (
    BRAND_INTEL,
    DEAL_SCORING,
    HERRAMIENTAS,
    RESEARCH,
    id_de,
    medir_uso,
    registrar_uso,
    resumen_de_uso,
)


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


@pytest.fixture()
def sesion_del_contador(db, monkeypatch):
    """El contador abre su PROPIA sesión (a propósito: si la ruta falla y su transacción se
    revierte, la corrida ocurrió igual). Acá se la apunta a la base del test."""
    import shared.database.session as sess

    monkeypatch.setattr(sess, "SessionLocal", lambda: db)
    # `db.close()` del contador cerraría la sesión del test a mitad de camino.
    monkeypatch.setattr(db, "close", lambda: None)
    return db


# ── El registro ──────────────────────────────────────────────────────────────────

def test_una_corrida_deja_su_fila_con_el_sujeto(sesion_del_contador):
    registrar_uso(herramienta=RESEARCH, accion="respuesta", user_id="u1",
                  sujeto="¿Cómo está la resiliencia energética?")
    fila = sesion_del_contador.query(ToolRun).one()
    assert (fila.herramienta, fila.accion, fila.user_id) == (RESEARCH, "respuesta", "u1")
    assert "resiliencia" in fila.sujeto
    assert fila.ok is True and len(fila.periodo) == 7


def test_una_corrida_que_FALLA_tambien_se_cuenta(sesion_del_contador):
    """Una herramienta cara que falla cuesta igual. Contar solo los éxitos oculta justo eso."""
    with pytest.raises(RuntimeError):
        with medir_uso(herramienta=DEAL_SCORING, accion="score", user_id="u1"):
            raise RuntimeError("la corrida reventó")
    fila = sesion_del_contador.query(ToolRun).one()
    assert fila.ok is False, "la corrida fallida desapareció del contador"
    assert fila.latency_ms is not None


def test_el_sujeto_se_RECORTA_al_largo_de_su_columna(sesion_del_contador):
    """SQLite no aplica el largo de un VARCHAR y Postgres sí: sin recorte, un sujeto largo
    pasa todos los tests y tumba el registro en producción."""
    tope = ToolRun.__table__.c.sujeto.type.length
    registrar_uso(herramienta=RESEARCH, accion="respuesta", sujeto="x" * (tope + 500))
    assert len(sesion_del_contador.query(ToolRun).one().sujeto) == tope


def test_el_contador_NUNCA_tumba_la_herramienta(monkeypatch):
    """Sin base, sin sesión, con lo que sea: la instrumentación se traga su fallo."""
    import shared.database.session as sess

    def revienta():
        raise RuntimeError("no hay base")

    monkeypatch.setattr(sess, "SessionLocal", revienta)
    registrar_uso(herramienta=RESEARCH, accion="respuesta")  # no debe lanzar
    with medir_uso(herramienta=RESEARCH, accion="respuesta"):
        pass


def test_el_id_de_quien_corre_es_defensivo():
    """Leer `user.id` es lo único que ocurre FUERA del best-effort. Un doble de test sin ese
    atributo no puede tumbar la ruta de la herramienta."""
    class SinId:
        pass

    assert id_de(SinId()) is None
    assert id_de(None) is None


# ── El resumen ───────────────────────────────────────────────────────────────────

def test_cada_conteo_NOMBRA_su_poblacion(sesion_del_contador):
    """«corridas» a secas se reatribuye al sujeto más cercano en cuanto sale de la función."""
    registrar_uso(herramienta=RESEARCH, accion="respuesta", user_id="u1")
    registrar_uso(herramienta=RESEARCH, accion="entregable", user_id="u2")
    r = resumen_de_uso(sesion_del_contador)
    fila = next(f for f in r["por_herramienta"] if f["herramienta"] == RESEARCH)
    assert fila["corridas_de_la_herramienta"] == 2
    assert fila["usuarios_distintos_de_la_herramienta"] == 2
    assert "corridas_totales_de_las_herramientas" in r
    assert {f["accion"] for f in r["por_accion"]} == {"respuesta", "entregable"}


def test_una_herramienta_SIN_corridas_se_lista_en_cero(sesion_del_contador):
    """«Nadie la usó» y «no existe» son respuestas comercialmente opuestas, y un catálogo que
    solo muestra lo usado no las distingue."""
    registrar_uso(herramienta=RESEARCH, accion="respuesta")
    r = resumen_de_uso(sesion_del_contador)
    listadas = {f["herramienta"] for f in r["por_herramienta"]}
    assert listadas >= set(HERRAMIENTAS), f"faltan del listado: {set(HERRAMIENTAS) - listadas}"
    marca = next(f for f in r["por_herramienta"] if f["herramienta"] == BRAND_INTEL)
    assert marca["corridas_de_la_herramienta"] == 0


def test_las_fallidas_se_muestran_aparte_y_no_se_restan(sesion_del_contador):
    registrar_uso(herramienta=DEAL_SCORING, accion="score", ok=True)
    registrar_uso(herramienta=DEAL_SCORING, accion="score", ok=False)
    fila = next(f for f in resumen_de_uso(sesion_del_contador)["por_herramienta"]
                if f["herramienta"] == DEAL_SCORING)
    assert fila["corridas_de_la_herramienta"] == 2
    assert fila["corridas_fallidas_de_la_herramienta"] == 1


#: Un día CUALQUIERA pero FIJO. El rango se prueba contra instantes elegidos, nunca contra
#: el reloj de quien corre los tests: sellar con «ahora» ataba el veredicto a la hora del día.
_DIA = date(2026, 5, 14)


def _corrida_sellada_en(db, cuando: datetime) -> None:
    """Una fila con su sello puesto A MANO, para poder pararse en los bordes del día."""
    db.add(ToolRun(herramienta=RESEARCH, accion="respuesta", ok=True,
                   periodo=cuando.strftime("%Y-%m"), created_at=cuando))
    db.commit()


def test_el_rango_incluye_el_DIA_COMPLETO_de_hasta(db):
    """Los DOS extremos del día de ``hasta``, no solo su medianoche.

    Tomar la fecha tal cual dejaría fuera todo el último día —el que más se mira— y el total
    seguiría siendo un número plausible.

    **Por qué el día es fijo y el sello se pone a mano.** Este test sembraba con «ahora» y
    preguntaba por ``date.today()``, que es el reloj LOCAL: pasadas las 20:00 AST el sello
    —que viaja en UTC— ya era del día siguiente y quedaba fuera del rango, así que el test se
    ponía rojo por la hora en que se lo corría y no por el código bajo prueba. En CI, que
    corre en UTC, no se veía nunca. Un test de rango que solo tiene dientes en cierta franja
    horaria no es un test de rango.
    """
    _corrida_sellada_en(db, datetime.combine(_DIA, time(0, 0, 0)))
    _corrida_sellada_en(db, datetime.combine(_DIA, time(23, 59, 59)))

    r = resumen_de_uso(db, desde=_DIA, hasta=_DIA)
    assert r["corridas_totales_de_las_herramientas"] == 2, (
        "el rango se comió un extremo del día de 'hasta'")
    assert (r["desde"], r["hasta"]) == (_DIA.isoformat(), _DIA.isoformat())


def test_el_reloj_QUE_SELLA_es_el_MISMO_que_FILTRA(sesion_del_contador):
    """Una corrida de recién entra en el rango por defecto — y «hoy» es UNO solo.

    Es la costura que el test anterior ya no cruza: el sello lo pone la base y el rango lo
    arma el motor, y si los dos relojes se separan la corrida desaparece del panel sin que
    falle nada. El síntoma —un número más bajo— se lee como «se usó menos», que es una
    conclusión comercial equivocada. Se afirma contra UTC y no contra ``date.today()``
    porque el motor, los otros tres paneles y el frontend arman el rango en UTC.
    """
    registrar_uso(herramienta=RESEARCH, accion="respuesta")
    ahora_utc = datetime.now(timezone.utc).replace(tzinfo=None)

    fila = sesion_del_contador.query(ToolRun).one()
    desfase_s = abs((fila.created_at - ahora_utc).total_seconds())
    assert desfase_s < 60, (
        f"el sello de la corrida está {desfase_s:.0f}s del reloj que arma el rango: son dos "
        "relojes distintos y las corridas del borde del día se pierden")

    r = resumen_de_uso(sesion_del_contador)
    assert r["corridas_totales_de_las_herramientas"] == 1


# ── Por HTTP: la ruta de la herramienta, y la del panel ──────────────────────────

class _Admin:
    id = "admin-1"
    role = UserRole.admin
    organization_id = None
    email = "admin@sdq.test"


def test_por_HTTP_scorear_un_deal_deja_su_corrida(sesion_del_contador):
    """El contador vive en la RUTA, no en el motor: se pide por HTTP o no se probó."""
    from app.deal_scoring_api import router
    from shared.auth.dependencies import get_current_user

    app = FastAPI()
    app.include_router(router, prefix="/api/v1/deal-scoring")
    app.dependency_overrides[get_db] = lambda: sesion_del_contador
    app.dependency_overrides[get_current_user] = lambda: _Admin()

    r = TestClient(app).post("/api/v1/deal-scoring/score", json={
        "deal_name": "Proyecto Piloto", "deal_type": "capital_raise", "sector": "fintech",
        "country": "DO", "deal_stage": "due_diligence", "deal_size_usd": 5_000_000,
        "equity_required_pct": 30, "promoter_track_record": 75, "financial_quality": 68,
        "with_ai": False,
    })
    assert r.status_code == 200, r.text

    fila = sesion_del_contador.query(ToolRun).filter(
        ToolRun.herramienta == DEAL_SCORING).one()
    assert (fila.accion, fila.user_id, fila.sujeto) == ("score", "admin-1", "Proyecto Piloto")
    assert fila.detalle["con_ia"] is False


def test_por_HTTP_el_panel_del_operador_sirve_el_resumen(sesion_del_contador):
    from shared.auth.dependencies import get_current_user
    from shared.operations.router import router

    registrar_uso(herramienta=RESEARCH, accion="respuesta", user_id="u1")
    app = FastAPI()
    app.include_router(router, prefix="/api/v1/operations")
    app.dependency_overrides[get_db] = lambda: sesion_del_contador
    app.dependency_overrides[get_current_user] = lambda: _Admin()

    r = TestClient(app).get("/api/v1/operations/uso-de-herramientas")
    assert r.status_code == 200, r.text
    cuerpo = r.json()
    assert cuerpo["corridas_totales_de_las_herramientas"] == 1
    assert {f["herramienta"] for f in cuerpo["por_herramienta"]} >= set(HERRAMIENTAS)


def test_por_HTTP_un_rango_invertido_se_rechaza(sesion_del_contador):
    from shared.auth.dependencies import get_current_user
    from shared.operations.router import router

    app = FastAPI()
    app.include_router(router, prefix="/api/v1/operations")
    app.dependency_overrides[get_db] = lambda: sesion_del_contador
    app.dependency_overrides[get_current_user] = lambda: _Admin()

    r = TestClient(app).get("/api/v1/operations/uso-de-herramientas",
                            params={"desde": "2026-09-09", "hasta": "2026-09-01"})
    assert r.status_code == 400


def test_por_HTTP_el_panel_es_de_ADMIN(sesion_del_contador):
    from shared.auth.dependencies import get_current_user
    from shared.operations.router import router

    class _Viewer(_Admin):
        role = UserRole.viewer

    app = FastAPI()
    app.include_router(router, prefix="/api/v1/operations")
    app.dependency_overrides[get_db] = lambda: sesion_del_contador
    app.dependency_overrides[get_current_user] = lambda: _Viewer()

    assert TestClient(app).get(
        "/api/v1/operations/uso-de-herramientas").status_code == 403


def test_una_corrida_PERDIDA_deja_rastro_en_el_log(monkeypatch, caplog):
    """Se comprobó perdiendo una corrida real por un `database is locked` de SQLite: HTTP 200
    en la ruta, cero rastro en el contador y nada en ningún log. Un contador que subcuenta en
    silencio es peor que no tenerlo — el síntoma se lee como «se usó menos»."""
    import logging

    import shared.database.session as sess

    def revienta():
        raise RuntimeError("database is locked")

    monkeypatch.setattr(sess, "SessionLocal", revienta)
    with caplog.at_level(logging.WARNING, logger="sdq.observability.uso_de_herramientas"):
        registrar_uso(herramienta=RESEARCH, accion="respuesta")
    assert any(r.levelno >= logging.WARNING for r in caplog.records), (
        "la corrida se perdió sin dejar rastro")
    assert "subcontar" in caplog.text
