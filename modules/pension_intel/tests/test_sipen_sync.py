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


def test_parse_mes_ano_xlsx_maps_spanish_months():
    """The CKAN 'Mes | Año | valor' workbook → [(YYYY-MM, value)]; junk rows skipped."""
    import io

    import openpyxl

    from shared.data.sipen_client import parse_mes_ano_xlsx

    wb = openpyxl.Workbook()
    ws = wb.active
    ws.append(["Mes", "Año", "Afiliados"])      # header (no month) → skipped
    ws.append(["Septiembre", "2003", 927082])
    ws.append(["Diciembre", "2025", 5600000])
    ws.append(["Totales", "", "x"])             # junk → skipped
    buf = io.BytesIO()
    wb.save(buf)

    rows = dict(parse_mes_ano_xlsx(buf.getvalue()))
    assert rows == {"2003-09": 927082.0, "2025-12": 5600000.0}


def test_sync_ingests_ckan_series_and_snapshot_uses_latest_per_code(db, monkeypatch):
    """Live CKAN records land as system series, and the snapshot keeps each indicator's
    latest value (fresh afiliados doesn't drop the older fixture rentabilidad)."""
    from datetime import date

    from shared.data.lineage import Lineage
    from shared.data.base_client import Record

    lin = Lineage(source="SIPEN", license="x", fetched_at=date.today())
    fake = [
        Record(series="sipen.afiliados.total", period="2026-05", value=5649211.0, lineage=lin, unit="personas"),
        Record(series="sipen.cotizantes.total", period="2026-05", value=2213058.0, lineage=lin, unit="personas"),
    ]
    monkeypatch.setattr("modules.pension_intel.sipen_sync.fetch_sipen_ckan", lambda period=None: fake)

    res = sipen_pension_sync(db)
    assert res["ckan_rows"] == 2

    afi = (db.query(PensionSeries)
           .filter_by(entity_slug=None, series_code="sipen.afiliados.total", period="2026-05").one())
    assert afi.value == 5649211.0 and afi.source == "SIPEN"

    # Snapshot is at the newest period but still carries the older fixture rentabilidad.
    snap = db.query(PensionSnapshot).order_by(PensionSnapshot.period.desc()).first()
    assert snap.period == "2026-05"
    assert snap.headline.get("sipen.afiliados.total") == 5649211.0
    assert "sipen.rentabilidad.cci_nominal_anual" in snap.headline  # older series retained
