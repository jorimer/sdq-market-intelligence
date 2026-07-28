"""Tests de API de la vista Histórico (TestClient) — cubre los endpoints + la narrativa
async (path degradado, el entorno de test no tiene ANTHROPIC_API_KEY)."""
from datetime import date

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from shared.database.base import Base
from shared.database.session import get_db
from shared.auth.dependencies import get_current_user
from shared.auth.models import User, UserRole
from modules.banking_score.models.models import SibHistoricalFinancials as F
from app.main import app

engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
TestSession = sessionmaker(bind=engine)


def _override_db():
    db = TestSession()
    try:
        yield db
    finally:
        db.close()


def _fake_user():
    return User(id="u1", email="t@sdq.do", password_hash="x", full_name="T", role=UserRole.admin)


client = TestClient(app)


@pytest.fixture(autouse=True)
def _db():
    # Overrides SOLO durante estos tests, con save/restore — un override a nivel de módulo
    # sobre el `app` compartido contamina a otros suites (p.ej. la auth de test_api.py).
    Base.metadata.create_all(engine, tables=[F.__table__])
    saved = dict(app.dependency_overrides)
    app.dependency_overrides[get_db] = _override_db
    app.dependency_overrides[get_current_user] = _fake_user
    db = TestSession()
    y, m = 2001, 1
    for i in range(18):
        mora = 1.0 if i < 12 else 40.0
        cob = 200.0 if i < 12 else 20.0
        db.add(F(entidad_nombre="Banco Quebrado", entidad_code="BQ", tipo_entidad="Bancos Múltiples",
                 sector="Privado", fecha=date(y, m, 1), ano=y, mes=m,
                 activos_totales=1000, depositos_totales=600, morosidad_pct=mora,
                 cobertura_pct=cob, apalancamiento_pct=10.0))
        m += 1
        if m > 12:
            m, y = 1, y + 1
    db.commit()
    db.close()
    yield
    app.dependency_overrides.clear()
    app.dependency_overrides.update(saved)
    Base.metadata.drop_all(engine)


def test_entities_and_cohort():
    assert client.get("/api/v1/banking-score/historical/entities").status_code == 200
    r = client.get("/api/v1/banking-score/historical/cohort")
    assert r.status_code == 200 and "cohort" in r.json()


def test_forensic_package_endpoint():
    r = client.get("/api/v1/banking-score/historical/forensic", params={"nombre": "Banco Quebrado"})
    assert r.status_code == 200
    assert r.json()["meta"]["nombre"] == "Banco Quebrado"
    assert client.get("/api/v1/banking-score/historical/forensic",
                      params={"nombre": "No Existe"}).status_code == 404


def test_forensic_narrative_and_report():
    # Robusto al entorno: en CI (sin ANTHROPIC_API_KEY) la narrativa degrada; en local con
    # key genera. No asertamos el valor de 'degraded', solo la mecánica del endpoint.
    r = client.get("/api/v1/banking-score/historical/forensic/narrative",
                   params={"nombre": "Banco Quebrado"})
    assert r.status_code == 200
    body = r.json()
    assert isinstance(body["degraded"], bool) and body["nombre"] == "Banco Quebrado"
    # el informe branded se sirve como HTML aunque la narrativa esté degradada
    rep = client.get("/api/v1/banking-score/historical/forensic/report",
                     params={"nombre": "Banco Quebrado"})
    assert rep.status_code == 200
    assert rep.headers["content-type"] == "application/pdf"
    assert rep.content.startswith(b"%PDF")
