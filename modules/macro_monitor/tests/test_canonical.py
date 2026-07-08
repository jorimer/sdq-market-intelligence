"""Canonical registry integrity + canonical-only ingestion."""
from datetime import date
from types import SimpleNamespace

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from shared.data.base_client import Record
from shared.data.bcrd_excel import canonical
from shared.data.bcrd_excel.catalog import find_entry
from shared.data.lineage import Lineage
from shared.database.base import Base
from modules.macro_monitor.models.models import ExcelFileReport, MacroSeries  # noqa: F401
from modules.macro_monitor import service


@pytest.fixture()
def db():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(bind=engine)
    session = sessionmaker(bind=engine)()
    try:
        yield session
    finally:
        session.close()
        Base.metadata.drop_all(bind=engine)


def test_registry_integrity():
    reg = canonical.registry()
    assert len(reg) >= 20
    keys = [s.key for s in reg]
    assert len(keys) == len(set(keys))  # unique keys
    # every canonical source file actually exists in the catalog
    for s in reg:
        assert find_entry(s.source_file) is not None, f"falta en catálogo: {s.source_file}"
    # robustness is one of the three states
    assert all(s.robustness in ("green", "yellow", "red") for s in reg)
    # API-tied series declare how to compare
    assert all(s.api_transform in ("identity", "yoy") for s in reg if s.api_series)


def test_get_canonical_registry_attaches_extraction(db):
    reg = canonical.registry()
    sample = reg[0]
    db.add(ExcelFileReport(file_url="u", filename=sample.source_file, sector=sample.sector,
                           status="ok", method="heuristic", n_series=3, orientation="period_rows"))
    db.commit()
    out = service.get_canonical_registry(db)
    assert out["count"] == len(reg)
    row = next(r for r in out["series"] if r["key"] == sample.key)
    assert row["extraction"]["status"] == "ok" and row["extraction"]["n_series"] == 3
    # a series whose file has no report yet shows extraction=None
    assert any(r["extraction"] is None for r in out["series"])


def test_ingest_canonical_dedupes_and_persists(db, monkeypatch):
    def fake(entry, **kw):
        lin = Lineage(source="BCRD", license="x", fetched_at=date.today())
        recs = [Record(series="bcrd.xls.f.s", period="2020", value=1.0, lineage=lin)]
        report = SimpleNamespace(ok=True, series=[SimpleNamespace(code="bcrd.xls.f.s", flags=[])], flagged=[])
        spec = SimpleNamespace(method="heuristic", orientation="period_rows", frequency="annual", confidence=0.8)
        return SimpleNamespace(file=entry.filename, spec=spec, records=recs, report=report)

    monkeypatch.setattr("shared.data.bcrd_excel.engine.ingest_excel", fake)
    out = service.ingest_canonical(db, persist=True)
    # reserves brutas+netas share one file → unique files < total registry entries
    assert out["files"] < len(canonical.registry())
    assert out["ok"] >= 1
    assert db.query(ExcelFileReport).count() == out["files"]
    assert db.query(MacroSeries).count() >= 1  # persisted


def test_imae_canonical_points_to_current_base2018_file():
    """El BCRD migró el IMAE a imae_2018.xlsx (base 2018); el viejo imae.xlsx quedó
    congelado en oct-2024. El canónico debe apuntar al vigente y estar en el catálogo."""
    imae = next(s for s in canonical.registry() if s.key == "imae")
    assert imae.source_file == "imae_2018.xlsx"
    assert imae.base == "2018=100"
    assert find_entry(imae.source_file) is not None  # resoluble en el catálogo
