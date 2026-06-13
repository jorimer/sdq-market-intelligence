"""Batch runner over the catalog + coverage rollup (engine mocked, offline)."""
from datetime import date
from types import SimpleNamespace

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from shared.data.base_client import Record
from shared.data.lineage import Lineage
from shared.database.base import Base
from modules.macro_monitor.models.models import ExcelFileReport, MacroSeries  # noqa: F401
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


def _result(ok=True, n=2):
    lin = Lineage(source="BCRD", license="x", fetched_at=date.today())
    recs = [Record(series="bcrd.xls.f.s", period=f"200{i}", value=float(i), lineage=lin) for i in range(n)]
    sr = SimpleNamespace(code="bcrd.xls.f.s", flags=[] if ok else ["pocas observaciones"])
    report = SimpleNamespace(ok=ok, series=[sr], flagged=[] if ok else [sr])
    spec = SimpleNamespace(method="heuristic", orientation="matrix", frequency="annual", confidence=0.8)
    return SimpleNamespace(file="f.xls", spec=spec, records=recs, report=report)


def test_batch_writes_reports_and_rollup(db, monkeypatch):
    calls = {"n": 0}

    def fake_ingest(entry, **kw):
        calls["n"] += 1
        if calls["n"] == 2:
            raise RuntimeError("descarga falló")     # one failure
        return _result(ok=(calls["n"] != 3))          # one flagged (#3), rest ok

    monkeypatch.setattr("shared.data.bcrd_excel.engine.ingest_excel", fake_ingest)
    out = service.run_excel_batch(db, limit=4, use_claude=False)
    assert out["processed"] == 4
    assert out["ok"] == 2 and out["failed"] == 1 and out["flagged"] == 1

    cov = service.get_excel_coverage(db)
    assert cov["reported"] == 4
    assert cov["by_status"] == {"ok": 2, "failed": 1, "flagged": 1}
    assert cov["total_catalog"] == 708
    # flagged + failed surface in the attention list with their detail
    statuses = {a["status"] for a in cov["attention"]}
    assert statuses == {"flagged", "failed"}
    assert any(a["error"] for a in cov["attention"] if a["status"] == "failed")
    assert not cov["status"]["is_running"]


def test_batch_persist_series_upserts(db, monkeypatch):
    monkeypatch.setattr("shared.data.bcrd_excel.engine.ingest_excel", lambda e, **k: _result(n=3))
    service.run_excel_batch(db, limit=1, use_claude=False, persist_series=True)
    assert db.query(MacroSeries).count() == 3   # records written
    row = db.query(ExcelFileReport).first()
    assert row.persisted == 3 and row.status == "ok"


def test_batch_idempotent_resume(db, monkeypatch):
    monkeypatch.setattr("shared.data.bcrd_excel.engine.ingest_excel", lambda e, **k: _result())
    service.run_excel_batch(db, limit=2, use_claude=False)
    # a second run without force skips already-reported files (no re-ingest)
    seen = {"n": 0}

    def counting(e, **k):
        seen["n"] += 1
        return _result()

    monkeypatch.setattr("shared.data.bcrd_excel.engine.ingest_excel", counting)
    out = service.run_excel_batch(db, limit=2, use_claude=False)
    assert seen["n"] == 0 and out["ok"] == 0   # nothing re-processed
    assert db.query(ExcelFileReport).count() == 2
