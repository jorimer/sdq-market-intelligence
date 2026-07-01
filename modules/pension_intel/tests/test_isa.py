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


def test_rankings_collapse_to_latest_period_per_afp(db):
    """An AFP with ratings at two periods must appear ONCE (the latest) in the ranking —
    a re-score at a newer statement period supersedes the older row, never duplicates it."""
    from modules.pension_intel.api.router import _ranked_ratings

    # Start from a clean slate for this AFP (the base sync may have scored it already).
    db.query(PensionRating).filter(PensionRating.entity_slug == "afp_jmmb_bdi").delete()
    # Two ratings for the same AFP: an old base period and a newer financials period.
    db.add(PensionRating(entity_slug="afp_jmmb_bdi", period="2025-04",
                         overall_score=None, band=None, coverage=0.3))
    db.add(PensionRating(entity_slug="afp_jmmb_bdi", period="2026-06",
                         overall_score=72.6, band="Adecuada", coverage=0.65))
    db.flush()

    ranked = _ranked_ratings(db)
    jmmb = [p for p in ranked if p["slug"] == "afp_jmmb_bdi"]
    assert len(jmmb) == 1, "the AFP must not appear twice"
    assert jmmb[0]["period"] == "2026-06" and jmmb[0]["band"] == "Adecuada"


def test_entity_detail_returns_latest_period(db):
    """The detail endpoint must return the AFP's newest rating, not a stale older-period
    row — an unordered .first() would surface the pre-financials 2025 rating."""
    import asyncio

    from modules.pension_intel.api.router import entity_detail

    db.query(PensionRating).filter(PensionRating.entity_slug == "afp_jmmb_bdi").delete()
    db.add(PensionRating(entity_slug="afp_jmmb_bdi", period="2025-04",
                         overall_score=None, band=None, coverage=0.3))
    db.add(PensionRating(entity_slug="afp_jmmb_bdi", period="2026-06",
                         overall_score=72.6, band="Adecuada", coverage=0.65))
    db.flush()

    res = asyncio.run(entity_detail("afp_jmmb_bdi", db=db, current_user=None))
    assert res["found"] is True
    assert res["period"] == "2026-06" and res["band"] == "Adecuada"


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


def test_rentabilidad_hybrid_communicates_magnitude(db):
    # Fase 6: híbrido banda-absoluta + min-max. El líder ya NO queda clavado en 100 ni el
    # rezagado en 0 — el score refleja MAGNITUD absoluta además del rango del panel.
    by_slug = {r["slug"]: r for r in compute_isa(db)}

    def rent(s):
        return next(d for d in by_slug[s]["dimensions"] if d["key"] == "rentabilidad")["score"]

    lead, lag = rent("afp_reservas"), rent("afp_atlantico")
    # Reservas (10.97%) lidera: banda absoluta ~85 + min-max 100 → híbrido ~92.6 (no 100).
    assert lead == pytest.approx(92.64, abs=0.2)
    # Atlántico (8.12%) rezaga pero su 8.12% real NO vale 0 (banda absoluta lo rescata).
    assert lag > 0.0
    assert lag == pytest.approx(22.29, abs=0.5)
    assert lead > lag  # se preserva el orden relativo


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


# ── Fase 2: costo dimension (unit fix + absolute scoring) ───────────────────────

def test_to_rd_normalizes_millions():
    from modules.pension_intel.scoring.isa import _to_rd
    assert _to_rd(2265.7, "RD$ MM") == pytest.approx(2265.7 * 1_000_000)
    assert _to_rd(2265.7, "RD$") == 2265.7
    assert _to_rd(100.0, None) == 100.0


def test_score_costo_absolute_band():
    from modules.pension_intel.scoring.isa import _score_costo_absolute
    assert _score_costo_absolute(0.4) == 100.0    # cheap
    assert _score_costo_absolute(1.2) == 0.0      # expensive
    assert _score_costo_absolute(0.8) == pytest.approx(50.0, abs=0.5)
    # a marginal 0.22pp real spread no longer spans the full 0-100 range (the min-max bug)
    assert _score_costo_absolute(0.65) - _score_costo_absolute(0.87) < 30


def test_costo_ratio_unit_normalized_and_absolute(tmp_path):
    """comisiones in 'RD$ MM' ÷ AUM in 'RD$' must yield a real % (~0.65), not ~0.0,
    and the cheapest AFP must NOT be min-max-inflated to a perfect 100."""
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    from sqlalchemy.pool import StaticPool
    from modules.pension_intel.models.models import PensionEntity, PensionSeries

    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    db = sessionmaker(bind=engine)()

    def seed(slug, comis_mm, aum_rd, rent):
        db.add(PensionEntity(slug=slug, name=slug, is_active=True))
        db.add(PensionSeries(entity_slug=slug, series_code="comisiones_anual",
                             period="2025", value=comis_mm, unit="RD$ MM", source="SIPEN"))
        db.add(PensionSeries(entity_slug=slug, series_code="fondos_administrados",
                             period="2026-05", value=aum_rd, unit="RD$", source="SIPEN"))
        db.add(PensionSeries(entity_slug=slug, series_code="rentabilidad_nominal_anual",
                             period="2026-05", value=rent, unit="%", source="SIPEN"))

    seed("afp_a", 2265.7, 348007034642.0, 8.0)   # ~0.65%  (cheapest)
    seed("afp_b", 99.2, 11377405992.0, 9.0)      # ~0.87%
    db.commit()

    res = {r["slug"]: r for r in compute_isa(db)}
    costo_a = next(d for d in res["afp_a"]["dimensions"] if d["key"] == "costo")
    costo_b = next(d for d in res["afp_b"]["dimensions"] if d["key"] == "costo")
    assert costo_a["raw"] == pytest.approx(0.65, abs=0.05)   # real %, not 0.0
    assert costo_a["score"] > costo_b["score"]               # A genuinely cheaper
    assert costo_a["score"] < 100.0                          # absolute band, not min-max top
    db.close()


# ── Fase 6: híbrido banda-absoluta + min-max ──────────────────────────────────

def test_absolute_band_linear_and_log_and_clamp():
    from modules.pension_intel.scoring.isa import _absolute_band
    # lineal rentabilidad 5→0, 12→100
    assert _absolute_band(5.0, 5.0, 12.0, False) == 0.0
    assert _absolute_band(12.0, 5.0, 12.0, False) == 100.0
    assert _absolute_band(8.5, 5.0, 12.0, False) == pytest.approx(50.0, abs=0.1)
    # clamp fuera de rango
    assert _absolute_band(3.0, 5.0, 12.0, False) == 0.0
    assert _absolute_band(20.0, 5.0, 12.0, False) == 100.0
    # log escala 10bn→0, 500bn→100; el punto medio geométrico (~70.7bn) ≈ 50
    import math
    mid = 10 ** ((math.log10(10e9) + math.log10(500e9)) / 2)
    assert _absolute_band(mid, 10e9, 500e9, True) == pytest.approx(50.0, abs=0.5)


def test_score_hybrid_blends_absolute_and_minmax():
    from modules.pension_intel.scoring.isa import _score_hybrid, _absolute_band, _normalize
    present = {"a": 10.97, "b": 8.5, "c": 6.5}  # rentabilidad (líder < ancla 12 → no clava 100)
    out = _score_hybrid(present, "rentabilidad", "higher")
    mm = _normalize(present, "higher")
    for s, v in present.items():
        ab = _absolute_band(v, 5.0, 12.0, False)
        assert out[s] == pytest.approx(0.5 * ab + 0.5 * mm[s], abs=0.01)
    # el líder no queda en 100 (magnitud) y el rezagado no en 0
    assert out["a"] < 100.0
    assert out["c"] > 0.0
    # orden preservado
    assert out["a"] > out["b"] > out["c"]
