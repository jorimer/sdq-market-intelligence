"""Tests for the ENAE structural-financial sync (Eje 3 · de-rubricize PR-1).

Offline: the "live" fetch is routed to the committed ``enae_activity.json`` fixture,
or made to raise, via monkeypatch. No network. Also covers the crosswalk partition
and the connector's fail-closed guards (present / partition / margin cross-check).
"""
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from shared.data.enae_activity import (
    EnaeActivityClient,
    EnaeError,
    build_records,
    VAR_INGRESOS,
    VAR_COSTOS,
    VAR_UTILIDAD,
    VAR_RENTABILIDAD,
)
from shared.data.sector_crosswalk import (
    ENAE_KEYS,
    enae_coverage,
    enae_members,
    map_enae_label,
)
from shared.database.base import Base
from shared.settings.models import AppSetting  # noqa: F401 — register app_setting table
from shared.reference.sector_variables import SectorVariable  # noqa: F401 — register tables
from modules.sector_intel.sectors_sync import ENAE_DIMENSION, enae_sync


@pytest.fixture
def db():
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    s = sessionmaker(bind=engine)()
    try:
        yield s
    finally:
        s.close()
        Base.metadata.drop_all(bind=engine)


def _offline(monkeypatch):
    """Route the live fetch to the committed fixture (stays offline)."""
    monkeypatch.setattr(EnaeActivityClient, "_fetch_live", EnaeActivityClient._fetch_fixture)


# ── Crosswalk ─────────────────────────────────────────────────────────────────
def test_crosswalk_is_partial_and_maps_comercio():
    cov = enae_coverage()
    assert cov["n_enae_sectors"] == 9
    # comercio is the headline retail sector and maps 1:1
    assert map_enae_label("Comercio") == "comercio"
    assert enae_members("comercio") == ["comercio"]
    # electricity + water both feed the single energia slug
    assert enae_members("electricidad") == ["energia"]
    assert enae_members("agua") == ["energia"]
    # manufactura is a declared bundle (ZF not separated)
    assert set(enae_members("manufactura")) == {"manufactura_local", "zonas_francas"}
    # partial coverage: the 8 service/primary slugs are honestly NOT covered
    assert "agropecuario" in cov["uncovered"] and "financiero" in cov["uncovered"]
    assert "comercio" in cov["covered"]


def test_map_label_tolerant_and_total_is_none():
    assert map_enae_label("  comercio ") == "comercio"          # case/space tolerant
    assert map_enae_label("Explotación de minas y canteras") == "minas"
    assert map_enae_label("Total") is None                     # the aggregate row
    assert map_enae_label("Fuente: ENAE") is None              # a note row


# ── Connector guards (pure, no I/O) ─────────────────────────────────────────────
def _good_parsed():
    """Minimal valid parsed set: 9 sectors, one year, margin-consistent."""
    ing = {k: {2022: 100.0} for k in ENAE_KEYS}
    cos = {k: {2022: 80.0} for k in ENAE_KEYS}
    uti = {k: {2022: 20.0} for k in ENAE_KEYS}
    ren = {k: {2022: 0.20} for k in ENAE_KEYS}        # 20/100 = 0.20 ✓
    parsed = {VAR_INGRESOS: ing, VAR_COSTOS: cos, VAR_UTILIDAD: uti, VAR_RENTABILIDAD: ren}
    totals = {v: {2022: 100.0 * len(ENAE_KEYS)} if v != VAR_RENTABILIDAD else {}
              for v in (VAR_INGRESOS, VAR_COSTOS, VAR_UTILIDAD, VAR_RENTABILIDAD)}
    # costs/profit totals must match their own Σ (80*9, 20*9)
    totals[VAR_COSTOS] = {2022: 80.0 * len(ENAE_KEYS)}
    totals[VAR_UTILIDAD] = {2022: 20.0 * len(ENAE_KEYS)}
    return parsed, totals


def test_build_records_happy_path():
    parsed, totals = _good_parsed()
    recs = build_records(parsed, totals)
    assert len(recs) == 4 * len(ENAE_KEYS)            # 4 vars × 9 sectors × 1 year
    assert all(r.dimension in ENAE_KEYS for r in recs)


def test_guard_missing_sector_raises():
    parsed, totals = _good_parsed()
    del parsed[VAR_INGRESOS]["comercio"]              # drop a sector
    with pytest.raises(EnaeError, match="ausentes"):
        build_records(parsed, totals)


def test_guard_partition_deviation_raises():
    parsed, totals = _good_parsed()
    totals[VAR_INGRESOS] = {2022: 1.0}               # Σ (900) won't match Total (1)
    with pytest.raises(EnaeError, match="Σ sectores"):
        build_records(parsed, totals)


def test_guard_margin_mismatch_raises():
    parsed, totals = _good_parsed()
    parsed[VAR_RENTABILIDAD]["comercio"][2022] = 0.99   # ≠ 20/100
    with pytest.raises(EnaeError, match="rentabilidad"):
        build_records(parsed, totals)


# ── Fixture (real committed data) ───────────────────────────────────────────────
def test_fixture_has_real_comercio_panel():
    recs = EnaeActivityClient().fetch(series=VAR_INGRESOS, period="2022")
    comercio = next(r for r in recs if r.dimension == "comercio")
    assert comercio.value > 1_000_000        # comercio income 2022 ≈ 1.89M millones RD$
    assert comercio.unit == "millones RD$"


# ── Sync ────────────────────────────────────────────────────────────────────────
def test_sync_persists_sectors_with_provenance(db, monkeypatch):
    _offline(monkeypatch)
    res = enae_sync(db)
    assert res["errors"] == []
    assert res["synced"] == 4 * len(ENAE_KEYS) * 8       # 4 vars × 9 sectors × 8 years (2015-22)
    assert res["sectors"] == 9
    assert res["variables"] == sorted([VAR_COSTOS, VAR_INGRESOS, VAR_RENTABILIDAD, VAR_UTILIDAD])

    rows = db.query(SectorVariable).all()
    assert {r.sector_code for r in rows} == set(ENAE_KEYS)
    assert all(r.dimension == ENAE_DIMENSION for r in rows)
    sample = db.query(SectorVariable).filter_by(
        sector_code="comercio", variable=VAR_INGRESOS, period="2022").first()
    assert sample.source == "ONE" and sample.license
    assert "2015" in res["periods"] and "2022" in res["periods"]


def test_sync_is_idempotent(db, monkeypatch):
    _offline(monkeypatch)
    first = enae_sync(db)
    n1 = db.query(SectorVariable).count()
    assert n1 == first["synced"]
    second = enae_sync(db)                  # upsert in place — no duplicates
    assert db.query(SectorVariable).count() == n1
    assert second["synced"] == first["synced"]


def test_sync_best_effort_on_upstream_failure(db, monkeypatch):
    def _boom(self, series=None, period=None):
        raise EnaeError("landing caída")
    monkeypatch.setattr(EnaeActivityClient, "_fetch_live", _boom)
    res = enae_sync(db)                      # must NOT raise
    assert res["synced"] == 0
    assert res["errors"] and "landing caída" in res["errors"][0]
    assert db.query(SectorVariable).count() == 0


def test_enae_rows_do_not_pollute_the_iai(db, monkeypatch):
    """ENAE sector rows must not leak into the 17-slug index or its period grid."""
    from modules.sector_intel.service import (
        _sector_periods,
        assemble_iai_dataset,
        get_sector_variables,
    )

    db.add(SectorVariable(sector_code="turismo", dimension="sector",
                          variable="sector_size", value=8.9, period="2024", source="BCRD"))
    db.commit()
    _offline(monkeypatch)
    enae_sync(db)                            # adds ENAE 2015-2022 under dimension="enae"

    assert _sector_periods(db) == ["2024"]   # index period grid unchanged by ENAE years
    assert len(assemble_iai_dataset(db)["dataset"]) == 17
    sv = get_sector_variables(db)["sectors"]
    assert all(VAR_INGRESOS not in vars_ for vars_ in sv.values())
    assert "comercio" not in sv or "ingresos" not in sv.get("comercio", {})
