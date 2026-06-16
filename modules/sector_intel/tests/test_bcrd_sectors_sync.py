"""Tests for the BCRD value-added sector connector + sync (Eje 3 Gate A).

All offline: the pure builder is fed synthetic maps, and the sync runs against a
fixture-mode client (the committed ``bcrd_sectors.json``). No network.
"""
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from shared.database.base import Base
from shared.data.bcrd_sectors import (
    BCRDSectorsClient,
    BCRDSectorsError,
    SECTORS,
    TOTAL_LABEL,
    VAR_GROWTH,
    VAR_SIZE,
    _norm,
    build_sector_records,
)
from modules.sector_intel.models.models import (  # noqa: F401 — register tables
    Sector,
    SectorVariable,
)
from modules.sector_intel.sectors_sync import bcrd_sectores_sync

LABELS = [label for _slug, label, _name in SECTORS]  # all 17 leaf labels


def _nominal(year_values):
    """Build a full nominal map (all 17 leaves + Valor Agregado = their sum).

    ``year_values``: ``{label: {year: value}}`` covering every leaf. The
    builder is fail-closed, so a partial map would (correctly) raise.
    """
    nominal = {_norm(lbl): dict(year_values[lbl]) for lbl in LABELS}
    years = {y for d in year_values.values() for y in d}
    nominal[_norm(TOTAL_LABEL)] = {
        y: sum(year_values[lbl].get(y, 0.0) for lbl in LABELS) for y in years
    }
    return nominal


@pytest.fixture
def db():
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    Session = sessionmaker(bind=engine)
    s = Session()
    try:
        yield s
    finally:
        s.close()
        Base.metadata.drop_all(bind=engine)


# ── Pure builder ──────────────────────────────────────────────────
def test_size_is_share_of_value_added():
    vals = {lbl: {2024: 10.0} for lbl in LABELS}
    vals[LABELS[0]][2024] = 40.0   # Agropecuario
    vals[LABELS[4]][2024] = 60.0   # Construcción
    va = 40.0 + 60.0 + 10.0 * (len(LABELS) - 2)  # = 250
    recs = build_sector_records(_nominal(vals), {}, url=None)
    sizes = {r.dimension: r.value for r in recs if r.series == VAR_SIZE and r.period == "2024"}
    assert sizes["agropecuario"] == pytest.approx(100.0 * 40.0 / va)
    assert sizes["construccion"] == pytest.approx(100.0 * 60.0 / va)
    assert sum(v for v in sizes.values() if v is not None) == pytest.approx(100.0)


def test_growth_is_real_yoy_and_none_without_prior_year():
    nominal = _nominal({lbl: {2023: 10.0, 2024: 10.0} for lbl in LABELS})
    real = {_norm(lbl): {2023: 100.0, 2024: 100.0} for lbl in LABELS}
    real[_norm(LABELS[0])] = {2023: 100.0, 2024: 110.0}  # Agropecuario +10% real
    recs = build_sector_records(nominal, real, url=None)
    g = {r.period: r.value for r in recs if r.series == VAR_GROWTH and r.dimension == "agropecuario"}
    assert g["2023"] is None          # no prior year → not fabricated
    assert g["2024"] == pytest.approx(10.0)


def test_missing_value_added_raises():
    with pytest.raises(BCRDSectorsError):
        build_sector_records({_norm(LABELS[0]): {2024: 1.0}}, {}, url=None)


def test_partition_deviation_fails_closed():
    # Value Added inflated beyond the leaf sum → must raise, not persist skewed shares.
    nominal = _nominal({lbl: {2024: 10.0} for lbl in LABELS})  # leaf sum = 170
    nominal[_norm(TOTAL_LABEL)][2024] = 200.0                  # claims 200 → −15%
    with pytest.raises(BCRDSectorsError):
        build_sector_records(nominal, {}, url=None)


def test_missing_leaf_fails_closed():
    # A renamed/removed leaf breaks the partition → fail closed (anti double-count).
    nominal = _nominal({lbl: {2024: 10.0} for lbl in LABELS})
    del nominal[_norm(LABELS[3])]
    with pytest.raises(BCRDSectorsError):
        build_sector_records(nominal, {}, url=None)


def test_norm_is_accent_and_case_insensitive():
    # A BCRD rename to different casing/accents must still match the same slug.
    assert _norm("CONSTRUCCION") == _norm("Construcción")
    assert _norm("Servicios Profesionales") == _norm("Servicios profesionales")


# ── Fixture-mode client (offline) ─────────────────────────────────
def test_fixture_client_returns_full_catalog():
    recs = BCRDSectorsClient(mode="fixture").fetch()
    assert recs, "fixture vacío — ¿se generó bcrd_sectors.json?"
    sectors = {r.dimension for r in recs}
    assert len(sectors) == len(SECTORS) == 17
    # for the latest year, sizes sum to ~100%
    latest = max(r.period for r in recs)
    sizes = [r.value for r in recs if r.series == VAR_SIZE and r.period == latest and r.value is not None]
    assert sum(sizes) == pytest.approx(100.0, abs=0.5)


# ── Sync (offline via fixture monkeypatch) ────────────────────────
def test_sync_persists_and_is_idempotent(db, monkeypatch):
    # Route the "live" fetch to the committed fixture so the test stays offline.
    monkeypatch.setattr(BCRDSectorsClient, "_fetch_live", BCRDSectorsClient._fetch_fixture)

    first = bcrd_sectores_sync(db)
    assert first["errors"] == []
    assert first["synced"] > 0
    assert first["sectors_seeded"] == 17
    assert set(first["variables"]) == {VAR_SIZE, VAR_GROWTH}
    n1 = db.query(SectorVariable).count()
    assert n1 == first["synced"]

    # second run upserts in place — no duplicate rows, same count, no re-seed.
    second = bcrd_sectores_sync(db)
    assert second["sectors_seeded"] == 0
    n2 = db.query(SectorVariable).count()
    assert n2 == n1

    # a known row is stamped with provenance
    row = (
        db.query(SectorVariable)
        .filter_by(sector_code="turismo", variable=VAR_SIZE)
        .first()
    )
    assert row is not None
    assert row.source == "BCRD"
    assert row.dimension == "sector"
