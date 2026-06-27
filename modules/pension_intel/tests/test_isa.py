"""Tests for the Índice de Solidez de AFP (ISA) — scoring + persistence + honesty."""
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from shared.database.base import Base
from modules.pension_intel.models.models import PensionRating
from modules.pension_intel.scoring.isa import band_for, compute_isa
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
    sipen_pension_sync(session)  # ingests + scores + persists
    try:
        yield session
    finally:
        session.close()


def test_band_for_boundaries():
    assert band_for(80) == "Sólida"
    assert band_for(60) == "Adecuada"
    assert band_for(45) == "En vigilancia"
    assert band_for(10) == "Frágil"
    assert band_for(None) is None


def test_solvency_absent_until_financials_caps_coverage(db):
    """Without estados financieros, solvency is absent → coverage ≤ 0.65, bands deferred."""
    results = compute_isa(db)
    assert results, "expected ISA results"
    for r in results:
        solv = next(d for d in r["dimensions"] if d["key"] == "solvencia")
        # Solvency is a real ratio dim, but absent (no patrimonio/activos series yet).
        assert solv["present"] is False
        assert r["coverage"] <= 0.65 + 1e-9
        assert r["band"] is None  # no absolute band until solvency lands


def test_full_vs_thin_coverage(db):
    by_slug = {r["slug"]: r for r in compute_isa(db)}
    # Popular has rentabilidad + escala + costo → coverage 0.65.
    assert by_slug["afp_popular"]["coverage"] == pytest.approx(0.65, abs=1e-6)
    # Romana has only rentabilidad → coverage 0.30.
    assert by_slug["afp_romana"]["coverage"] == pytest.approx(0.30, abs=1e-6)


def test_rentabilidad_peer_extremes(db):
    by_slug = {r["slug"]: r for r in compute_isa(db)}

    def rent(s):
        return next(d for d in by_slug[s]["dimensions"] if d["key"] == "rentabilidad")["score"]

    # Reservas leads rentabilidad (10.97) → 100; Atlántico lags (8.12) → 0.
    assert rent("afp_reservas") == 100.0
    assert rent("afp_atlantico") == 0.0


def test_ratings_persisted_and_sorted(db):
    rows = db.query(PensionRating).all()
    assert len(rows) == 7  # every AFP gets a row…
    # …but only those above the coverage gate carry a relative score (the 3 with full public data).
    scored_rows = [r for r in rows if r.overall_score is not None]
    assert {r.entity_slug for r in scored_rows} == {"afp_popular", "afp_crecer", "afp_siembra"}
    scored = [r for r in compute_isa(db) if r["overall_score"] is not None]
    scores = [r["overall_score"] for r in scored]
    assert scores == sorted(scores, reverse=True)


def test_absolute_bands_are_deferred(db):
    """F2 ships a RELATIVE partial score; absolute health bands wait for solvency."""
    rows = db.query(PensionRating).all()
    assert all(r.band is None for r in rows)
    for r in compute_isa(db):
        assert r["band"] is None and r["score_kind"] == "relative_partial"


def test_thin_coverage_afp_is_unscored(db):
    by_slug = {r["slug"]: r for r in compute_isa(db)}
    # Romana (only rentabilidad, coverage 0.30 < gate) gets no band/score, but its
    # rentabilidad dimension is still shown (transparent, not hidden).
    romana = by_slug["afp_romana"]
    assert romana["scoreable"] is False
    assert romana["overall_score"] is None and romana["band"] is None
    rent = next(d for d in romana["dimensions"] if d["key"] == "rentabilidad")
    assert rent["present"] is True and rent["score"] is not None


def test_no_solvency_figure_fabricated(db):
    """The gap stays a gap — solvency raw value is never invented."""
    for r in compute_isa(db):
        solv = next(d for d in r["dimensions"] if d["key"] == "solvencia")
        assert solv["raw"] is None and solv["score"] is None
