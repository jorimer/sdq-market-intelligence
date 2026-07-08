"""Router tests for the BCRD publications endpoints in macro_monitor."""
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from shared.auth.dependencies import get_current_user, require_role
from shared.auth.models import UserRole
from shared.database.base import Base
from shared.database.session import get_db
from shared.publications.models import Publication
from modules.macro_monitor.api.router import router


@pytest.fixture()
def db():
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(engine, tables=[Publication.__table__])
    Session = sessionmaker(bind=engine)
    s = Session()
    try:
        yield s
    finally:
        s.close()


def _seed(db, key, period, sectors, status="ok", resumen="resumen"):
    row = Publication(
        report_key=key, report_name=key, period=period, title=f"{key} {period}",
        sectors=sectors, status=status, source_url="http://x/y.pdf",
        digest={"resumen": resumen, "hallazgos": ["h1"], "cifras": [], "riesgos": [], "relevancia": {}},
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


def _client(db, role=UserRole.admin):
    app = FastAPI()
    app.include_router(router, prefix="/api/v1/macro-monitor")

    class _U:
        def __init__(self, r):
            self.role = r

    app.dependency_overrides[get_db] = lambda: db
    app.dependency_overrides[get_current_user] = lambda: _U(role)
    # require_role returns a fresh dependency callable per-route; override the factory's
    # result by overriding get_current_user (require_role depends on it).
    return TestClient(app)


def test_list_publications(db):
    _seed(db, "politica_monetaria", "2025-06", ["macro"])
    _seed(db, "estabilidad_financiera", "2024-12", ["banca", "macro"])
    c = _client(db)
    r = c.get("/api/v1/macro-monitor/publications")
    assert r.status_code == 200
    body = r.json()
    assert body["count"] == 2
    assert {p["report_key"] for p in body["publications"]} == {
        "politica_monetaria", "estabilidad_financiera",
    }
    # summary carries resumen but not raw text
    assert "resumen" in body["publications"][0]
    assert "raw_text" not in body["publications"][0]


def test_list_filter_by_report(db):
    _seed(db, "politica_monetaria", "2025-06", ["macro"])
    _seed(db, "estabilidad_financiera", "2024-12", ["banca"])
    c = _client(db)
    r = c.get("/api/v1/macro-monitor/publications", params={"report_key": "politica_monetaria"})
    assert r.json()["count"] == 1


def test_catalog_reports_latest_period(db):
    _seed(db, "politica_monetaria", "2024-12", ["macro"])
    _seed(db, "politica_monetaria", "2025-06", ["macro"])
    c = _client(db)
    r = c.get("/api/v1/macro-monitor/publications/catalog")
    assert r.status_code == 200
    reports = {x["key"]: x for x in r.json()["reports"]}
    assert reports["politica_monetaria"]["latest_ingested_period"] == "2025-06"
    assert reports["estabilidad_financiera"]["latest_ingested_period"] is None
    assert reports["politica_monetaria"]["cadence"] == "trimestral"


def test_detail_includes_full_digest(db):
    row = _seed(db, "politica_monetaria", "2025-06", ["macro"], resumen="texto largo")
    c = _client(db)
    r = c.get(f"/api/v1/macro-monitor/publications/{row.id}")
    assert r.status_code == 200
    assert r.json()["digest"]["resumen"] == "texto largo"


def test_detail_404(db):
    c = _client(db)
    r = c.get("/api/v1/macro-monitor/publications/nope")
    assert r.status_code == 404


def test_refresh_unknown_report_400(db):
    c = _client(db)
    r = c.post("/api/v1/macro-monitor/publications/refresh", params={"report_key": "no_existe"})
    assert r.status_code == 400


def test_refresh_invokes_ingest(db, monkeypatch):
    from modules.macro_monitor.api import router as rt

    def fake_ingest(_db, key, force=False):
        return _seed(_db, key, "2025-06", ["macro"])

    monkeypatch.setattr(rt.pub_service, "ingest_report", fake_ingest)
    c = _client(db)
    r = c.post("/api/v1/macro-monitor/publications/refresh", params={"report_key": "politica_monetaria"})
    assert r.status_code == 200
    body = r.json()
    assert body["ingested_ok"] == 1
    assert body["results"][0]["period"] == "2025-06"


def test_refresh_reports_unavailable(db, monkeypatch):
    from modules.macro_monitor.api import router as rt

    monkeypatch.setattr(rt.pub_service, "ingest_report", lambda _db, key, force=False: None)
    c = _client(db)
    r = c.post("/api/v1/macro-monitor/publications/refresh", params={"report_key": "politica_monetaria"})
    assert r.status_code == 200
    body = r.json()
    assert body["ingested_ok"] == 0
    assert body["results"][0]["status"] == "unavailable"
