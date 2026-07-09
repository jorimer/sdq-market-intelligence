"""Regresión E2E-TE1: ``/telecom-intel/score`` etiquetaba la fuente como "INDOTEL" fija,
pese a que INDOTEL quedó congelado en 2022-Q1 y la serie vigente es ITU DataHub. La fuente
se infiere del período: con "Q" = boletín INDOTEL (histórico); sin "Q" = ITU DataHub.

Los overrides de dependencias se aplican y se RESTAURAN dentro de un fixture para no
contaminar el ``app`` compartido con otros módulos de test (mismo objeto FastAPI).
"""
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.main import app
from shared.database.base import Base
from shared.database.session import get_db
from shared.auth.dependencies import get_current_user
from modules.telecom_intel.models.models import TelecomScore

engine = create_engine("sqlite://", connect_args={"check_same_thread": False},
                       poolclass=StaticPool)
TestSession = sessionmaker(bind=engine)


@pytest.fixture()
def client():
    Base.metadata.create_all(engine, tables=[TelecomScore.__table__])

    def _override_db():
        db = TestSession()
        try:
            yield db
        finally:
            db.close()

    prev = dict(app.dependency_overrides)
    app.dependency_overrides[get_db] = _override_db
    app.dependency_overrides[get_current_user] = lambda: object()
    try:
        yield TestClient(app)
    finally:
        app.dependency_overrides.clear()
        app.dependency_overrides.update(prev)
        Base.metadata.drop_all(engine, tables=[TelecomScore.__table__])


def _seed(period: str):
    db = TestSession()
    db.query(TelecomScore).delete()
    db.add(TelecomScore(period=period, telecom_score=70.0, band="Medio",
                        coverage=1.0, breakdown={"dimensions": {}, "metrics": {}}))
    db.commit()
    db.close()


def test_annual_period_is_itu(client):
    _seed("2024")
    r = client.get("/api/v1/telecom-intel/score")
    assert r.status_code == 200
    assert r.json()["source"] == "ITU DataHub"


def test_quarterly_period_is_indotel_historic(client):
    _seed("2021-Q4")
    r = client.get("/api/v1/telecom-intel/score")
    assert r.status_code == 200
    assert r.json()["source"] == "INDOTEL (histórico)"
