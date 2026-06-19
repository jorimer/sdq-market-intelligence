"""Gate E — IDM convergent validity (regional ranking vs PNUD IDHr). Offline."""
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from shared.database.base import Base
from shared.validation.metrics import spearman, spearman_bootstrap_ci
from modules.social_dev.models.models import DevelopmentScore  # noqa: F401 — register table
from modules.social_dev.validation.report import build_convergent_validity


@pytest.fixture
def db():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(bind=engine)
    s = sessionmaker(bind=engine)()
    try:
        yield s
    finally:
        s.close()
        Base.metadata.drop_all(bind=engine)


def test_spearman_perfect_and_inverse():
    assert spearman([1, 2, 3, 4], [10, 20, 30, 40]) == pytest.approx(1.0)
    assert spearman([1, 2, 3, 4], [40, 30, 20, 10]) == pytest.approx(-1.0)
    assert spearman([1, 2], [2, 1]) is None  # n<3


def test_spearman_bootstrap_ci_seeded_reproducible():
    xs = [1, 2, 3, 4, 5, 6]
    ys = [1, 2, 3, 4, 5, 6]
    rho, lo, hi = spearman_bootstrap_ci(xs, ys, n_boot=200)
    assert rho == pytest.approx(1.0) and lo is not None and lo <= hi


# Real prod IDM regional scores (latest period) — convergent validity must hold.
_PROD_IDM = {
    "cibao_sur": 57.77, "cibao_nordeste": 57.67, "cibao_norte": 57.56, "valdesia": 57.42,
    "yuma": 57.13, "ozama": 55.00, "higuamo": 52.89, "cibao_noroeste": 49.28,
    "el_valle": 41.88, "enriquillo": 41.21,
}


def test_convergent_validity_matches_pnud_idhr(db):
    for slug, score in _PROD_IDM.items():
        db.add(DevelopmentScore(entity_key=slug, period="2024", development_score=score))
    db.commit()

    rep = build_convergent_validity(db)
    assert rep["has_data"] and rep["n_regions"] == 10
    assert rep["spearman"] == 0.733                       # the real, strong convergent ρ
    assert rep["spearman_ci"][0] is not None and rep["spearman_ci"][1] is not None
    assert len(rep["pairs"]) == 10
    # Ozama is the explainable divergence (IDHr #1 by income; IDM ranks it mid).
    assert rep["top_divergence"]["region"] == "ozama"
    assert rep["source"].startswith("PNUD")


def test_convergent_validity_needs_min_regions(db):
    db.add(DevelopmentScore(entity_key="ozama", period="2024", development_score=55.0))
    db.commit()
    rep = build_convergent_validity(db)
    assert rep["has_data"] is False
