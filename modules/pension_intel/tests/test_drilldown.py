"""Tests for the per-indicator drill-down endpoints (Sistema / AFP / Cartera)."""
import asyncio
import json
import os

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from shared.database.base import Base
from modules.pension_intel.api.router import (
    afp_dimension,
    cartera_holding,
    system_indicator,
)
from modules.pension_intel.cartera_sync import persist_cartera
from modules.pension_intel.external.cartera_extractor import parse_cartera_words
from modules.pension_intel.sipen_sync import sipen_pension_sync

_FIXTURE = os.path.join(os.path.dirname(__file__), "fixtures", "cartera_p31_words.json")


@pytest.fixture()
def db():
    engine = create_engine("sqlite:///:memory:",
                           connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine, autoflush=False)()
    sipen_pension_sync(session)  # system + per-AFP series + ratings (live stubbed by conftest)
    with open(_FIXTURE, encoding="utf-8") as fh:
        persist_cartera(session, "2026-Q1", parse_cartera_words(json.load(fh)))
    session.commit()
    try:
        yield session
    finally:
        session.close()


def _run(coro):
    return asyncio.run(coro)


def test_system_indicator_returns_level_and_trend(db):
    res = _run(system_indicator(code="sipen.rentabilidad.cci_nominal_anual", with_ai=False,
                                audience="inversionista", deep=False, db=db, current_user=None))
    assert res["found"] is True
    assert res["label"] == "Rentabilidad nominal CCI" and res["unit"] == "%"
    assert res["latest"]["value"] == 9.4 and res["latest"]["period"] == "2025-04"
    assert res["trend"] and res["ai_insight"] is None  # with_ai=False → no narrative


def test_system_indicator_unknown_code(db):
    res = _run(system_indicator(code="nope", with_ai=False, audience="x", deep=False,
                                db=db, current_user=None))
    assert res["found"] is False


def test_afp_dimension_returns_value_peers_and_rank(db):
    res = _run(afp_dimension(slug="afp_siembra", key="rentabilidad", with_ai=False,
                             audience="inversionista", deep=False, db=db, current_user=None))
    assert res["found"] is True and res["afp"] == "AFP Siembra"
    assert res["dimension"]["key"] == "rentabilidad" and res["dimension"]["raw"] == 10.27
    # peers carry every AFP's value for this dimension (the panel comparison).
    assert len(res["peers"]) == 7
    assert any(p["afp"] == "AFP Reservas" for p in res["peers"])


def test_afp_dimension_unknown(db):
    assert _run(afp_dimension(slug="afp_siembra", key="bogus", with_ai=False, audience="x",
                              deep=False, db=db, current_user=None))["found"] is False
    assert _run(afp_dimension(slug="afp_nope", key="rentabilidad", with_ai=False, audience="x",
                              deep=False, db=db, current_user=None))["found"] is False


def test_cartera_holding_returns_position_with_cross_key(db):
    res = _run(cartera_holding(issuer_slug="ministerio_de_hacienda", period=None, fund="cci",
                               with_ai=False, audience="inversionista", deep=False,
                               db=db, current_user=None))
    assert res["found"] is True
    assert res["holding"]["issuer"] == "Ministerio de Hacienda"
    assert res["holding"]["pct"] == 56.04 and res["holding"]["macro_class"] == "deuda_publica"
    assert res["total"] > 0


def test_cartera_holding_unknown(db):
    res = _run(cartera_holding(issuer_slug="nope", period=None, fund="cci", with_ai=False,
                               audience="x", deep=False, db=db, current_user=None))
    assert res["found"] is False
