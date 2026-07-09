"""Regresión E2E-SYS1: el insight por-país de ESG/IRC ahora expone ``panel_position``
(rank/percentil/distribución) como campo estructurado, no solo dentro de la prosa IA.

Overrides de dependencias aplicados y RESTAURADOS en fixture (``app`` compartido).
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
from modules.esg_climate.models.models import ESGScore

engine = create_engine("sqlite://", connect_args={"check_same_thread": False},
                       poolclass=StaticPool)
TestSession = sessionmaker(bind=engine)


@pytest.fixture()
def client():
    Base.metadata.create_all(engine, tables=[ESGScore.__table__])

    def _override_db():
        db = TestSession()
        try:
            yield db
        finally:
            db.close()

    prev = dict(app.dependency_overrides)
    app.dependency_overrides[get_db] = _override_db
    app.dependency_overrides[get_current_user] = lambda: object()
    # Panel de 4 países en el mismo período (DOM en el fondo).
    db = TestSession()
    db.query(ESGScore).delete()
    for ek, sc in [("DOM", 35.65), ("CRI", 62.0), ("PAN", 55.0), ("HTI", 20.0)]:
        db.add(ESGScore(entity_key=ek, period="2023", esg_score=sc, band="Media",
                        breakdown={}))
    db.commit()
    db.close()
    try:
        yield TestClient(app)
    finally:
        app.dependency_overrides.clear()
        app.dependency_overrides.update(prev)
        Base.metadata.drop_all(engine, tables=[ESGScore.__table__])


def test_insight_exposes_panel_position(client):
    r = client.get("/api/v1/esg-climate/DOM/insight")
    assert r.status_code == 200
    pp = r.json()["panel_position"]
    assert pp is not None
    assert pp["n"] == 4
    # DOM 35.65: por encima solo de HTI (20) → rank 3 de 4.
    assert pp["rank"] == 3
    assert 0 <= pp["percentile"] <= 100
    assert pp["distribution"]["max"] == 62.0
