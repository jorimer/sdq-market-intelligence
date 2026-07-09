"""Regresión E2E-F3: la sección ``peer_position`` del producto Macro/Riesgo-País debe
poblarse en el tier **Insight** (antes solo se poblaba en Deep Dive, dejando la sección
"Posición en el Panel" hueca en el Insight aunque el panel del período existiera).
"""
import datetime as dt

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from shared.database.base import Base
from shared.products import ProductTier
from app.products_macro import MacroProduct
from modules.macro_political_risk.models.models import (
    Country,
    IRMPSnapshot,
    RiskBand,
)


@pytest.fixture()
def db():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False},
                           poolclass=StaticPool)
    Base.metadata.create_all(
        engine,
        tables=[Country.__table__, IRMPSnapshot.__table__],
    )
    s = sessionmaker(bind=engine)()
    try:
        yield s
    finally:
        s.close()


def _seed_panel(db, period=dt.date(2024, 12, 31)):
    """DO + 2 peers con snapshot en el mismo período (panel de 3)."""
    rows = [("DO", "República Dominicana", 46.06, RiskBand.elevado),
            ("CR", "Costa Rica", 58.0, RiskBand.moderado),
            ("PA", "Panamá", 51.0, RiskBand.moderado)]
    for iso, name, score, band in rows:
        c = Country(iso_code=iso, name=name, region="LATAM", is_active=True)
        db.add(c)
        db.flush()
        db.add(IRMPSnapshot(country_id=c.id, period_end=period, irmp_score=score,
                            risk_band=band, peer_set_size=len(rows),
                            breakdown={"macro": {"score": 42.0, "weight": 0.3,
                                                 "contribution": 12.6, "variables": {}}}))
    db.commit()
    return period


def test_insight_populates_peer_position(db):
    period = _seed_panel(db)
    snap = MacroProduct(db).snapshot(ProductTier.insight, str(period), scope="DO")
    pp = snap.payload.get("peer_position")
    assert pp, "El Insight debe traer peer_position (antes salía hueco)"
    assert pp["n_countries"] == 3
    # DO (46.06) es el de mayor riesgo → último del panel de 3 (rank 3).
    assert pp["rank"] == 3
    assert pp["distribution"]["max"] == 58.0


def test_deep_dive_still_populates_peer_position(db):
    period = _seed_panel(db)
    snap = MacroProduct(db).snapshot(ProductTier.deep_dive, str(period), scope="DO")
    assert snap.payload.get("peer_position"), "Deep Dive no debe regresionar"
    assert snap.payload["peer_position"]["rank"] == 3
