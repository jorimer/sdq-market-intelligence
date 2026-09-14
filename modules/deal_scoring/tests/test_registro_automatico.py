"""Cada corrida de scoring deja su fila, sin label, separada del registro curado (Fase 4b).

Se pide por HTTP (`POST /api/v1/deal-scoring/score`) con el router real del scorer y el del
registro montados juntos, como en `app/main.py`. Solo se falsean los anchors de los ejes y la
narrativa: la rúbrica, el registro y la curva son los reales.
"""
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from shared.auth.dependencies import get_current_user
from shared.auth.models import UserRole
from shared.database.base import Base
from shared.database.session import get_db
from modules.deal_scoring.models.models import (
    DealStage,
    DealType,
    HistoricalDeal,
    LabelConfidence,
    Sector,
)
from modules.deal_scoring.registro import ORIGEN_AUTOMATICO, ORIGEN_MANUAL

PREFIJO = "/api/v1/deal-scoring"

CUERPO = {
    "deal_name": "Proyecto Prueba", "deal_type": "capital_raise", "sector": "fintech",
    "country": "DO", "deal_stage": "due_diligence", "deal_size_usd": 5_000_000,
    "equity_required_pct": 30, "promoter_track_record": 75, "financial_quality": 68,
    "days_since_first_contact": 45, "with_ai": False,
}


@pytest.fixture()
def db():
    from shared.observability.models import ToolRun

    engine = create_engine("sqlite://", connect_args={"check_same_thread": False},
                           poolclass=StaticPool)
    Base.metadata.create_all(engine, tables=[HistoricalDeal.__table__, ToolRun.__table__])
    s = sessionmaker(bind=engine)()
    try:
        yield s
    finally:
        s.close()


@pytest.fixture()
def cliente(db, monkeypatch):
    import app.deal_scoring_api as api
    import shared.database.session as sess
    from modules.deal_scoring.api.router import router as registro

    # El contador de uso abre SU propia sesión contra la base de la app (a propósito: una
    # corrida cuenta aunque la ruta falle). Se apunta a la base del test, igual que en
    # `shared/observability/tests/test_uso_de_herramientas.py`; sin esto escribiría en el
    # archivo de desarrollo o fallaría en silencio.
    monkeypatch.setattr(sess, "SessionLocal", lambda: db)
    monkeypatch.setattr(db, "close", lambda: None)

    monkeypatch.setattr(api, "_fetch_anchors",
                        lambda db, c, s: {"values": {"country_irmp": 60.0, "country_irc": None,
                                                     "sector_iai": 55.0}, "sources": {}})
    app = FastAPI()
    app.include_router(api.router, prefix=PREFIJO)
    app.include_router(registro, prefix=PREFIJO)

    class _U:
        id = "u1"
        role = UserRole.admin

    app.dependency_overrides[get_db] = lambda: db
    app.dependency_overrides[get_current_user] = lambda: _U()
    return TestClient(app)


def _curado(db, nombre, closed=None):
    d = HistoricalDeal(deal_name=nombre, deal_type=DealType.capital_raise, sector=Sector.fintech,
                       country="DO", deal_stage=DealStage.due_diligence,
                       closed_successfully=closed, retrospective=False,
                       label_confidence=LabelConfidence.baja)
    db.add(d)
    db.commit()
    return d


# ── La corrida deja su fila ───────────────────────────────────────────────────────

def test_una_corrida_de_scoring_por_HTTP_crea_la_fila_SIN_label(cliente, db):
    r = cliente.post(f"{PREFIJO}/score", json=CUERPO)
    assert r.status_code == 200, r.text
    assert r.json()["registro"] == {"guardado": True, "origen": ORIGEN_AUTOMATICO,
                                    "deal_name": "Proyecto Prueba"}
    fila = db.query(HistoricalDeal).one()
    assert fila.origen == ORIGEN_AUTOMATICO
    assert fila.closed_successfully is None and fila.outcome_date is None
    assert fila.retrospective is False, "una corrida previa al desenlace es ex-ante"
    assert fila.score_rubrica == pytest.approx(r.json()["score"])
    assert fila.score_confianza in ("alta", "media", "baja")
    assert fila.promoter_track_record == 75 and fila.market_validation is None


def test_scorear_DOS_veces_el_mismo_deal_actualiza_UNA_fila(cliente, db):
    cliente.post(f"{PREFIJO}/score", json=CUERPO)
    cliente.post(f"{PREFIJO}/score", json={**CUERPO, "financial_quality": 90})
    filas = db.query(HistoricalDeal).filter_by(origen=ORIGEN_AUTOMATICO).all()
    assert len(filas) == 1 and filas[0].financial_quality == 90


@pytest.mark.parametrize("campo, valor", [("deal_type", "no_existe"), ("sector", None),
                                          ("country", ""), ("deal_name", " ")])
def test_sin_los_campos_obligatorios_NO_se_guarda_y_se_dice(cliente, db, campo, valor):
    r = cliente.post(f"{PREFIJO}/score", json={**CUERPO, campo: valor})
    assert r.status_code == 200, "el score se devuelve igual"
    assert r.json()["registro"]["guardado"] is False
    assert campo in r.json()["registro"]["motivo"]
    assert db.query(HistoricalDeal).count() == 0


def test_el_pais_NO_se_completa_con_DO_por_defecto(cliente, db):
    cuerpo = dict(CUERPO)
    cuerpo.pop("country")
    r = cliente.post(f"{PREFIJO}/score", json=cuerpo)
    assert r.json()["registro"]["guardado"] is False
    assert db.query(HistoricalDeal).count() == 0


def test_una_fila_con_DESENLACE_no_se_reescribe(cliente, db):
    """Guardar como ex-ante las entradas de un deal cuyo resultado ya se conoce es fuga."""
    cliente.post(f"{PREFIJO}/score", json=CUERPO)
    cliente.patch(f"{PREFIJO}/deals/Proyecto Prueba/outcome?origen={ORIGEN_AUTOMATICO}",
                  json={"closed_successfully": True})
    r = cliente.post(f"{PREFIJO}/score", json={**CUERPO, "financial_quality": 10})
    assert r.json()["registro"]["guardado"] is False
    fila = db.query(HistoricalDeal).filter_by(origen=ORIGEN_AUTOMATICO).one()
    assert fila.financial_quality == 68 and fila.closed_successfully is True


def test_un_fallo_al_guardar_NO_tumba_el_score(cliente, db, monkeypatch):
    import modules.deal_scoring.registro as reg

    def roto(*a, **k):
        raise RuntimeError("sin base")

    monkeypatch.setattr(reg.HistoricalDeal, "__init__", roto)
    r = cliente.post(f"{PREFIJO}/score", json=CUERPO)
    assert r.status_code == 200 and "score" in r.json()
    assert r.json()["registro"]["guardado"] is False


# ── El listado separa lo curado de lo automático ──────────────────────────────────

def test_GET_deals_lista_lo_automatico_SEPARADO_del_curado(cliente, db):
    _curado(db, "Deal curado")
    _curado(db, "Proyecto Prueba")                 # el mismo nombre también en el curado
    cliente.post(f"{PREFIJO}/score", json=CUERPO)
    body = cliente.get(f"{PREFIJO}/deals").json()
    assert {d["deal_name"] for d in body["deals"]} == {"Deal curado", "Proyecto Prueba"}
    assert all(d["origen"] == ORIGEN_MANUAL for d in body["deals"])
    assert [d["deal_name"] for d in body["deals_automaticos"]] == ["Proyecto Prueba"]
    assert body["count"] == 2, "el conteo del registro curado no puede mezclar lo automático"
    assert body["count_automaticos"] == 1


def test_el_PATCH_sin_origen_sigue_etiquetando_el_CURADO(cliente, db):
    """Compatibilidad con la pantalla actual, que no manda `origen`."""
    _curado(db, "Proyecto Prueba")
    cliente.post(f"{PREFIJO}/score", json=CUERPO)
    r = cliente.patch(f"{PREFIJO}/deals/Proyecto Prueba/outcome", json={"closed_successfully": False})
    assert r.status_code == 200
    curado = db.query(HistoricalDeal).filter_by(origen=ORIGEN_MANUAL).one()
    auto = db.query(HistoricalDeal).filter_by(origen=ORIGEN_AUTOMATICO).one()
    assert curado.closed_successfully is False and auto.closed_successfully is None


def test_un_origen_desconocido_en_el_PATCH_se_rechaza(cliente, db):
    cliente.post(f"{PREFIJO}/score", json=CUERPO)
    r = cliente.patch(f"{PREFIJO}/deals/Proyecto Prueba/outcome?origen=inventado",
                      json={"closed_successfully": True})
    assert r.status_code == 400


# ── La curva: ignora lo abierto y cuenta cada deal UNA vez ───────────────────────

def test_la_curva_IGNORA_la_fila_automatica_hasta_que_se_etiqueta(cliente, db):
    cliente.post(f"{PREFIJO}/score", json=CUERPO)
    assert cliente.get(f"{PREFIJO}/learning-curve").json()["n_labeled"] == 0
    cliente.patch(f"{PREFIJO}/deals/Proyecto Prueba/outcome?origen={ORIGEN_AUTOMATICO}",
                  json={"closed_successfully": True})
    curva = cliente.get(f"{PREFIJO}/learning-curve").json()
    assert curva["n_labeled"] == 1 and curva["n_ex_ante"] == 1


def test_un_deal_etiquetado_en_los_DOS_registros_cuenta_UNA_vez(cliente, db):
    """Sin esto, el mismo deal entra dos veces a la validación cruzada."""
    _curado(db, "Proyecto Prueba", closed=True)
    cliente.post(f"{PREFIJO}/score", json=CUERPO)
    cliente.patch(f"{PREFIJO}/deals/Proyecto Prueba/outcome?origen={ORIGEN_AUTOMATICO}",
                  json={"closed_successfully": True})
    assert cliente.get(f"{PREFIJO}/learning-curve").json()["n_labeled"] == 1
