"""Router tests del registro de deals — foco en el lazo de cosecha (PATCH outcome).

El PATCH cierra el lazo ex-ante: registra el desenlace de un deal ya en el registro
PRESERVANDO `retrospective` — un deal scoreado ex-ante sigue siendo ex-ante (y gradúa)
al conocerse su outcome; uno retrospectivo sigue retrospectivo (solo diagnóstico).
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
from modules.deal_scoring.api.router import router
from modules.deal_scoring.models.models import (
    DealStage, DealType, HistoricalDeal, LabelConfidence, Sector,
)


@pytest.fixture()
def db():
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(engine, tables=[HistoricalDeal.__table__])
    Session = sessionmaker(bind=engine)
    s = Session()
    try:
        yield s
    finally:
        s.close()


def _deal(db, name, *, closed=None, retrospective=False):
    d = HistoricalDeal(
        deal_name=name, deal_type=DealType.advisory, sector=Sector.other, country="DO",
        deal_stage=DealStage.due_diligence, deal_size_usd=1_000_000,
        closed_successfully=closed, retrospective=retrospective,
        label_confidence=LabelConfidence.baja,
    )
    db.add(d)
    db.commit()
    return d


def _client(db, role=UserRole.admin):
    app = FastAPI()
    app.include_router(router, prefix="/api/v1/deal-scoring")

    class _U:
        def __init__(self, r):
            self.role = r

    app.dependency_overrides[get_db] = lambda: db
    app.dependency_overrides[get_current_user] = lambda: _U(role)
    return TestClient(app)


def test_resolve_ex_ante_keeps_it_ex_ante(db):
    """Un deal ex-ante (cosecha) abierto → al registrar el desenlace SIGUE ex-ante:
    es el único camino que gradúa el modelo. El PATCH no debe flipear `retrospective`."""
    _deal(db, "Deal cosechado", closed=None, retrospective=False)
    c = _client(db)
    r = c.patch("/api/v1/deal-scoring/deals/Deal cosechado/outcome",
                json={"closed_successfully": True, "outcome_date": "2026-06-23"})
    assert r.status_code == 200
    body = r.json()
    assert body["resolved"] is True
    assert body["closed_successfully"] is True
    assert body["retrospective"] is False  # preservado
    assert body["outcome_date"] == "2026-06-23"
    got = db.query(HistoricalDeal).filter_by(deal_name="Deal cosechado").one()
    assert got.closed_successfully is True and got.retrospective is False


def test_resolve_retrospective_stays_retrospective(db):
    """Resolver un open retrospectivo (uno de los 98) NO lo vuelve ex-ante: sigue
    sujeto a fuga, solo nutre el diagnóstico. Preservar la marca es el núcleo anti-fuga."""
    _deal(db, "Open historico", closed=None, retrospective=True)
    c = _client(db)
    r = c.patch("/api/v1/deal-scoring/deals/Open historico/outcome",
                json={"closed_successfully": False})
    assert r.status_code == 200
    assert r.json()["retrospective"] is True
    got = db.query(HistoricalDeal).filter_by(deal_name="Open historico").one()
    assert got.closed_successfully is False and got.retrospective is True
    assert got.outcome_date is not None  # default = hoy


def test_resolve_accepts_spanish_outcome_words(db):
    """`_bool` acepta cerrado/perdido además de true/false."""
    _deal(db, "Deal ES", closed=None)
    c = _client(db)
    assert c.patch("/api/v1/deal-scoring/deals/Deal ES/outcome",
                   json={"closed_successfully": "perdido"}).json()["closed_successfully"] is False


def test_resolve_missing_outcome_is_400(db):
    _deal(db, "Sin outcome", closed=None)
    c = _client(db)
    r = c.patch("/api/v1/deal-scoring/deals/Sin outcome/outcome", json={})
    assert r.status_code == 400


def test_resolve_unknown_deal_is_404(db):
    c = _client(db)
    r = c.patch("/api/v1/deal-scoring/deals/No existe/outcome",
                json={"closed_successfully": True})
    assert r.status_code == 404


def test_resolve_requires_admin(db):
    _deal(db, "Protegido", closed=None)
    c = _client(db, role=UserRole.analyst)
    r = c.patch("/api/v1/deal-scoring/deals/Protegido/outcome",
                json={"closed_successfully": True})
    assert r.status_code == 403


def test_resolve_allows_super_admin(db):
    """super_admin es jerárquicamente ≥ admin → debe pasar (require_role), no 403.
    El front muestra los botones con hasRole('admin') jerárquico; el back debe alinearse."""
    _deal(db, "Super", closed=None)
    c = _client(db, role=UserRole.super_admin)
    r = c.patch("/api/v1/deal-scoring/deals/Super/outcome",
                json={"closed_successfully": True})
    assert r.status_code == 200
    assert r.json()["closed_successfully"] is True


def test_list_deals_exposes_retrospective_and_open_count(db):
    _deal(db, "ex1", closed=True, retrospective=False)
    _deal(db, "retro1", closed=False, retrospective=True)
    _deal(db, "open1", closed=None, retrospective=True)
    c = _client(db)
    body = c.get("/api/v1/deal-scoring/deals").json()
    assert body["count"] == 3
    assert body["n_labeled"] == 2
    assert body["n_ex_ante"] == 1
    assert body["n_open"] == 1
    by_name = {d["deal_name"]: d for d in body["deals"]}
    assert by_name["retro1"]["retrospective"] is True
    assert by_name["ex1"]["retrospective"] is False
