"""Regresión E2E-F4: integridad de snapshots IRMP.

Un dataset parcial (el smoke E2E con 3 variables) producía snapshots con dimensiones de
0 variables (score 0) que falseaban el índice, la trayectoria y el panel. Ahora:
- ``compute_and_persist`` rechaza datasets incompletos (no persiste basura).
- ``delete_invalid_snapshots`` limpia los inválidos ya persistidos (op de limpieza).
"""
import datetime as dt

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from shared.database.base import Base
from modules.macro_political_risk.models.models import (
    Country, IRMPSnapshot, DimensionScore, RiskBand,
)
from modules.macro_political_risk.service import (
    compute_and_persist, delete_invalid_snapshots, snapshot_breakdown_incomplete,
)


@pytest.fixture()
def db():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False},
                           poolclass=StaticPool)
    Base.metadata.create_all(
        engine, tables=[Country.__table__, IRMPSnapshot.__table__, DimensionScore.__table__])
    s = sessionmaker(bind=engine)()
    try:
        yield s
    finally:
        s.close()


def _full(**over):
    base = {"gdp_cagr_3y": 4.0, "inflation_gap": 1.0, "fiscal_balance_gdp": -3.0,
            "public_debt_gdp": 50.0, "reserves_import_months": 4.0,
            "current_account_gdp": -2.0, "fdi_gdp": 3.0, "fx_volatility": 3.0,
            "sovereign_rating_score": 50.0, "wgi_rule_of_law": 55.0,
            "wgi_gov_effectiveness": 55.0, "wgi_control_corruption": 45.0,
            "wgi_political_stability": 60.0, "wgi_voice_accountability": 60.0,
            "electoral_uncertainty": 30.0,
            "wgi_regulatory_quality": 55.0, "regulatory_volatility_5y": 25.0,
            "news_sentiment": -0.3, "unrest_shocks": 3.0, "sanctions_signal": 0.0}
    base.update(over)
    return base


PERIOD = dt.date(2024, 12, 31)


def test_complete_dataset_persists(db):
    ds = {"DO": _full(), "CR": _full(public_debt_gdp=63.0)}
    out = compute_and_persist(db, country_code="DO", dataset=ds, period_end=PERIOD)
    assert out["snapshot_id"]
    assert not snapshot_breakdown_incomplete(out["dimensions"])


def test_partial_dataset_rejected(db):
    # El dataset del smoke roto: 3 variables → dimensiones vacías → rechazado.
    ds = {"DO": {"gdp_cagr_3y": 5.0, "public_debt_gdp": 45.0, "wgi_rule_of_law": 55.0},
          "CR": {"gdp_cagr_3y": 3.0, "public_debt_gdp": 63.0, "wgi_rule_of_law": 65.0}}
    with pytest.raises(ValueError, match="incompleto"):
        compute_and_persist(db, country_code="DO", dataset=ds, period_end=PERIOD)
    # Y NO persistió nada.
    assert db.query(IRMPSnapshot).count() == 0


def test_cleanup_deletes_only_invalid(db):
    # Uno válido (persistido por el path real) + uno inválido inyectado a mano.
    compute_and_persist(db, country_code="DO", dataset={"DO": _full(), "CR": _full()},
                        period_end=PERIOD)
    do_country = db.query(Country).filter_by(iso_code="DO").first()
    db.add(IRMPSnapshot(country_id=do_country.id, period_end=dt.date(2025, 12, 31),
                        irmp_score=38.33, risk_band=RiskBand.alto,
                        breakdown={"macro": {"score": 100.0, "variables": {"x": 1}},
                                   "external": {"score": 0.0, "variables": {}},
                                   "events": {"score": 0.0, "variables": {}}}))
    db.commit()
    res = delete_invalid_snapshots(db)
    assert res["deleted"] == 1
    assert res["snapshots"][0]["period_end"] == "2025-12-31"
    # El válido sobrevive.
    remaining = db.query(IRMPSnapshot).all()
    assert len(remaining) == 1
    assert str(remaining[0].period_end) == "2024-12-31"


def test_incomplete_detector():
    assert snapshot_breakdown_incomplete(None) is True
    assert snapshot_breakdown_incomplete({}) is True
    assert snapshot_breakdown_incomplete({"macro": {"variables": {}}}) is True
    assert snapshot_breakdown_incomplete({"macro": {"variables": {"a": 1}}}) is False
