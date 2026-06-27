"""Tests for the SIPEN pension sync (fixture-backed, no network)."""
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from shared.database.base import Base
from shared.data.sipen_client import afp_catalog, sipen_client
from modules.pension_intel.sipen_sync import sipen_pension_sync
from modules.pension_intel.models.models import (
    PensionEntity,
    PensionSeries,
    PensionSnapshot,
)


@pytest.fixture()
def db():
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    # autoflush=False mirrors the shared SessionLocal (guards the snapshot-visibility bug).
    Session = sessionmaker(bind=engine, autoflush=False)
    session = Session()
    try:
        yield session
    finally:
        session.close()


def test_sync_seeds_entities_series_and_snapshot(db):
    res = sipen_pension_sync(db)

    # Every AFP in the catalog is seeded.
    assert res["entities_created"] == len(afp_catalog())
    assert db.query(PensionEntity).count() == len(afp_catalog())

    # System series (entity_slug NULL) and per-AFP series both land.
    system = db.query(PensionSeries).filter(PensionSeries.entity_slug.is_(None)).all()
    per_afp = db.query(PensionSeries).filter(PensionSeries.entity_slug.isnot(None)).all()
    assert {s.series_code for s in system} >= {
        "sipen.rentabilidad.cci_nominal_anual",
        "sipen.comisiones.total_anual",
    }
    assert per_afp, "expected per-AFP series"

    # A real, cited figure round-trips intact (no interpolation).
    siembra_ret = (
        db.query(PensionSeries)
        .filter(
            PensionSeries.entity_slug == "afp_siembra",
            PensionSeries.series_code == "rentabilidad_nominal_anual",
            PensionSeries.period == "2025-02",
        )
        .one()
    )
    assert siembra_ret.value == 10.27
    assert siembra_ret.source == "SIPEN"

    # Snapshot captures the latest system period's headline.
    snap = db.query(PensionSnapshot).one()
    assert res["snapshot_period"] == snap.period
    assert snap.headline.get("sipen.rentabilidad.cci_nominal_anual") == 9.4
    assert snap.entity_count == len(afp_catalog())


def test_sync_is_idempotent(db):
    first = sipen_pension_sync(db)
    n_after_first = db.query(PensionSeries).count()

    second = sipen_pension_sync(db)
    n_after_second = db.query(PensionSeries).count()

    # No duplicate rows, no duplicate entities on a second run.
    assert n_after_first == n_after_second
    assert second["entities_created"] == 0
    assert db.query(PensionEntity).count() == len(afp_catalog())
    assert db.query(PensionSnapshot).count() == 1


def test_fixture_has_no_invented_precision():
    """Sanity: the fixture only carries values we can cite (no fabricated numbers)."""
    system = sipen_client.fetch()
    codes = {r.series for r in system}
    assert "sipen.rentabilidad.cci_nominal_anual" in codes
    # Per-AFP rentabilidad present for all 7 administrators.
    ent = sipen_client.fetch_entities(series="rentabilidad_nominal_anual")
    assert {r.dimension for r in ent} == {slug for slug, _ in afp_catalog()}
