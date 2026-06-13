"""Service wiring for the BCRD Excel ingestion engine (catalog summary + upsert).

The engine itself is tested in ``shared/data/bcrd_excel``; here we only check the
macro_monitor seam: the catalog summary reads the real committed catalog, and
``ingest_excel_file`` upserts into MacroSeries only when not a dry run.
"""
from datetime import date
from types import SimpleNamespace

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from shared.data.base_client import Record
from shared.data.lineage import Lineage
from shared.database.base import Base
from modules.macro_monitor.models.models import MacroSeries  # noqa: F401 — register table
from modules.macro_monitor import service


@pytest.fixture()
def db():
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(bind=engine)
    Session = sessionmaker(bind=engine)
    session = Session()
    try:
        yield session
    finally:
        session.close()
        Base.metadata.drop_all(bind=engine)


def test_excel_catalog_summary_reads_real_catalog():
    summary = service.excel_catalog_summary()
    assert summary["total"] == 708
    assert summary["by_ext"].get(".xls", 0) > 400  # most of the corpus is legacy .xls
    assert "sector_externo" in summary["by_sector"]
    keys = {f["key"] for f in summary["featured"]}
    assert {"imae.xlsx", "ipc.xls", "reservas_internacionales.xlsx"} <= keys


def _fake_result():
    lin = Lineage(source="BCRD", license="x", fetched_at=date.today())
    recs = [
        Record(series="bcrd.xls.imae.indice", period="2007-01", value=93.96, lineage=lin, unit="x"),
        Record(series="bcrd.xls.imae.indice", period="2007-02", value=96.95, lineage=lin, unit="x"),
    ]
    report = SimpleNamespace(
        ok=True,
        series=[SimpleNamespace(code="bcrd.xls.imae.indice", unit="x", n_obs=2,
                                n_missing=0, period_min="2007-01", period_max="2007-02",
                                ok=True, flags=[])],
    )
    spec = SimpleNamespace(method="heuristic", confidence=0.85, orientation="period_rows")
    return SimpleNamespace(file="imae.xlsx", spec=spec, records=recs, report=report)


def test_ingest_excel_dry_run_does_not_persist(db, monkeypatch):
    monkeypatch.setattr(
        "shared.data.bcrd_excel.engine.ingest_excel", lambda *a, **k: _fake_result()
    )
    out = service.ingest_excel_file(db, key="imae.xlsx", dry_run=True)
    assert out["dry_run"] is True and out["touched"] == 0
    assert out["records"] == 2 and out["validation_ok"] is True
    assert db.query(MacroSeries).count() == 0  # nothing written


def test_ingest_excel_persist_upserts(db, monkeypatch):
    monkeypatch.setattr(
        "shared.data.bcrd_excel.engine.ingest_excel", lambda *a, **k: _fake_result()
    )
    out = service.ingest_excel_file(db, key="imae.xlsx", dry_run=False)
    assert out["dry_run"] is False and out["touched"] == 2
    assert db.query(MacroSeries).count() == 2
    row = db.query(MacroSeries).filter_by(period="2007-01").first()
    assert row.series_code == "bcrd.xls.imae.indice" and row.value == pytest.approx(93.96)


def test_ingest_excel_requires_key_or_url(db):
    with pytest.raises(ValueError):
        service.ingest_excel_file(db, dry_run=True)


def test_ingest_excel_unknown_key(db):
    with pytest.raises(ValueError):
        service.ingest_excel_file(db, key="no_existe_xyz.xlsx", dry_run=True)
