"""Tests for the pension system pulse + AI context + cerebro wiring."""
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from shared.database.base import Base
from modules.pension_intel.ai_context import pension_ai_context
from modules.pension_intel.service import build_system_pulse
from modules.pension_intel.sipen_sync import sipen_pension_sync


@pytest.fixture()
def db():
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine, autoflush=False)
    session = Session()
    sipen_pension_sync(session)
    try:
        yield session
    finally:
        session.close()


def test_pulse_has_headline_and_afp_dispersion(db):
    pulse = build_system_pulse(db)
    # Cronológicamente el período más nuevo del fixture es el anual "2025" (comisiones):
    # el año desnudo ordena después de sus meses (period_sort_key), y su snapshot as-of
    # ya incluye la rentabilidad de 2025-04.
    assert pulse["period"] == "2025"
    assert pulse["headline"]["sipen.rentabilidad.cci_nominal_anual"] == 9.4

    afp = pulse["afp_rentabilidad"]
    # Reservas leads (10.97), Atlántico lags (8.12) on 2025-02.
    assert afp["period"] == "2025-02"
    assert afp["leader"]["name"] == "AFP Reservas" and afp["leader"]["value"] == 10.97
    assert afp["laggard"]["name"] == "AFP Atlántico" and afp["laggard"]["value"] == 8.12
    assert afp["spread"] == round(10.97 - 8.12, 4)
    # Ranking is sorted descending and covers all 7 AFPs.
    assert len(afp["ranking"]) == 7
    assert afp["ranking"] == sorted(afp["ranking"], key=lambda d: d["value"], reverse=True)


def test_ai_context_is_compact_and_honest(db):
    ctx = pension_ai_context(build_system_pulse(db))
    assert ctx["rentabilidad_cci_nominal"] == 9.4
    assert ctx["afp_rentabilidad"]["lider"] == "AFP Reservas"
    assert ctx["afp_rentabilidad"]["brecha_pp"] == round(10.97 - 8.12, 4)
    # Honesty about nominal returns travels in the prompt.
    assert "NOMINAL" in ctx["note"]


def test_cerebro_axis_is_wired():
    from shared.narrative.cerebro import (
        AXIS_DOCTRINE,
        AUDIENCE_FRAMES,
        DEFAULT_AUDIENCE,
        build_system,
    )
    assert "pension_intel" in AXIS_DOCTRINE
    assert set(AUDIENCE_FRAMES["pension_intel"]) == {
        "inversionista", "regulador", "afiliado", "gobierno",
    }
    assert DEFAULT_AUDIENCE["pension_intel"] == "inversionista"
    # The thin template exists and the system prompt assembles without KeyError.
    from shared.narrative.claude_engine import THIN_TEMPLATES
    assert "pension_pulse" in THIN_TEMPLATES
    system = build_system("pension_intel", "regulador", "detailed")
    assert "sistema dominicano de pensiones" in system
    assert "Regulador / SIPEN" in system


def test_pulse_as_of_serves_historical_view(db, monkeypatch):
    """Regresión (espejo del PR #552 de seguros): elegir un período histórico debe
    servir la vista AS-OF, no el pulso actual con la etiqueta del período elegido."""
    from modules.pension_intel.tests.test_sipen_sync import _fake_rentabilidad_history

    monkeypatch.setattr("modules.pension_intel.sipen_sync.fetch_sipen_rentabilidad",
                        lambda period=None: _fake_rentabilidad_history())
    sipen_pension_sync(db)  # segundo sync idempotente: agrega la historia 2023-2024

    p = build_system_pulse(db, as_of="2023-06")
    assert p["period"] == "2023-06"
    # Headline as-of: la rentabilidad vigente en 2023-06, no la del último período.
    assert p["headline"]["sipen.rentabilidad.cci_nominal_anual"] == 8.5
    # Dispersión por AFP as-of: no ve observaciones posteriores al corte.
    assert p["afp_rentabilidad"]["period"] == "2023-06"
    assert p["afp_rentabilidad"]["leader"]["value"] == 8.0  # afp_siembra, 2023-06
    # Y difiere de la vista actual — no es el mismo reporte.
    latest = build_system_pulse(db)
    assert latest["headline"]["sipen.rentabilidad.cci_nominal_anual"] == 9.4
    assert latest["afp_rentabilidad"]["period"] == "2025-02"


def test_pulse_empty_when_no_data():
    engine = create_engine("sqlite:///:memory:", poolclass=StaticPool)
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine, autoflush=False)()
    pulse = build_system_pulse(session)
    assert pulse["afp_rentabilidad"]["ranking"] == []
    assert pulse["headline"] == {}
    session.close()
