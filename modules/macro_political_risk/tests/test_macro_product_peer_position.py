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
    # E2E-SYS1: percentil expuesto (rank 3 de 3 → 0.0, fondo del panel).
    assert pp["percentile"] == 0.0


def test_deep_dive_still_populates_peer_position(db):
    period = _seed_panel(db)
    snap = MacroProduct(db).snapshot(ProductTier.deep_dive, str(period), scope="DO")
    assert snap.payload.get("peer_position"), "Deep Dive no debe regresionar"
    assert snap.payload["peer_position"]["rank"] == 3


def _seed_do_trajectory(db):
    """3 cortes de DO (mejora sostenida) + 1 peer, para probar la trayectoria."""
    do = Country(iso_code="DO", name="República Dominicana", region="LATAM", is_active=True)
    cr = Country(iso_code="CR", name="Costa Rica", region="LATAM", is_active=True)
    db.add_all([do, cr])
    db.flush()
    for pe, score in [(dt.date(2024, 12, 31), 44.0),
                      (dt.date(2025, 6, 30), 46.0),
                      (dt.date(2025, 12, 31), 48.66)]:
        db.add(IRMPSnapshot(country_id=do.id, period_end=pe, irmp_score=score,
                            risk_band=RiskBand.elevado, peer_set_size=2, breakdown={}))
        db.add(IRMPSnapshot(country_id=cr.id, period_end=pe, irmp_score=58.0,
                            risk_band=RiskBand.moderado, peer_set_size=2, breakdown={}))
    db.commit()


def test_trajectory_as_of_latest_period(db):
    _seed_do_trajectory(db)
    snap = MacroProduct(db).snapshot(ProductTier.insight, "2025-12-31", scope="DO")
    traj = snap.payload.get("trajectory")
    assert traj, "El Insight debe traer trayectoria cuando hay ≥2 cortes"
    assert traj["n_periods"] == 3
    assert traj["series"][0]["period"] == "2024-12-31"   # cronológico
    assert traj["series"][-1]["period"] == "2025-12-31"
    assert traj["delta"] == 4.66   # 48.66 − 44.0, mejora sostenida


def test_trajectory_is_as_of_and_excludes_future(db):
    _seed_do_trajectory(db)
    # Reporte del primer corte: no hay historia previa → sin trayectoria (una foto).
    snap = MacroProduct(db).snapshot(ProductTier.insight, "2024-12-31", scope="DO")
    assert snap.payload.get("trajectory") in ({}, None)


def test_peer_position_needs_panel_of_two(db):
    # E2E-F4: panel de 1 país (solo DO en ese período) → sin peer_position (no "rank 1 de 1").
    do = Country(iso_code="DO", name="República Dominicana", region="LATAM", is_active=True)
    db.add(do)
    db.flush()
    db.add(IRMPSnapshot(country_id=do.id, period_end=dt.date(2025, 12, 31),
                        irmp_score=40.0, risk_band=RiskBand.alto, peer_set_size=1,
                        breakdown={}))
    db.commit()
    snap = MacroProduct(db).snapshot(ProductTier.insight, "2025-12-31", scope="DO")
    assert snap.payload.get("peer_position") in ({}, None)
