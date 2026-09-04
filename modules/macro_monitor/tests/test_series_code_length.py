"""Regresión del incidente 2026-06-13: el persist de las series canónicas daba
502 en prod (Postgres) con StringDataRightTruncation porque
``mm_series.series_code`` era VARCHAR(60), demasiado corto para los códigos
jerárquicos del motor Excel ("bcrd.xls.<archivo>.<métrica>", hasta ~95 chars).
SQLite no aplica la longitud, así que dev/tests no lo detectaban.

Estos tests fijan dos cosas: (1) la columna es lo bastante ancha para los códigos
del motor; (2) un upsert que falla no envenena la transacción y aborta toda la
ingesta canónica (el except hace rollback y continúa).
"""
from types import SimpleNamespace

from shared.data.base_client import Record
from shared.data.lineage import Lineage

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from shared.database.base import Base
from modules.macro_monitor import service
from modules.macro_monitor.models.models import ExcelFileReport, MacroSeries  # noqa: F401


# El código real más largo observado en el set canónico (ipc referencial).
LONGEST_CANONICAL_CODE = (
    "bcrd.xls.ipc_base_2019_2020_serie_referencial.variacion_porcentual_con_dic"
)


def test_series_code_column_fits_engine_codes():
    length = MacroSeries.__table__.c.series_code.type.length
    assert length is not None and length >= 120, (
        "mm_series.series_code debe ser holgado para los códigos del motor Excel "
        f"(el más largo conocido tiene {len(LONGEST_CANONICAL_CODE)} chars); "
        f"Postgres aplica la longitud y un cap corto da 502 en prod. length={length}"
    )
    assert length >= len(LONGEST_CANONICAL_CODE)


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


def test_ingest_canonical_continues_after_a_failing_file(db, monkeypatch):
    """Un archivo cuyo upsert falla se marca 'failed' y NO aborta el resto."""
    seen_files = []

    def fake_ingest(entry, **kwargs):
        seen_files.append(entry.filename)
        report = SimpleNamespace(ok=True, series=[], flagged=[])
        spec = SimpleNamespace(method="heuristic", orientation="period_rows",
                               frequency="monthly", confidence=0.9)
        # Un Record de verdad, no un `object()` opaco: por la ruta de escritura pasan
        # ahora otros pasos además del upsert (las unidades curadas del registro
        # canónico), y un centinela sin forma haría fallar la ingesta por un motivo que
        # no es el que este test mide.
        rec = Record(series="bcrd.xls.x.y", period="2020-01", value=1.0,
                     lineage=Lineage(source="BCRD", license="público"))
        return SimpleNamespace(records=[rec], report=report, spec=spec)

    # El primer archivo en procesarse revienta el upsert (simula la truncación);
    # los demás persisten normal. Sin el rollback, el reporte de fallo también
    # explotaría y abortaría la corrida.
    calls = {"n": 0}

    def fake_upsert(session, records):
        calls["n"] += 1
        if calls["n"] == 1:
            raise Exception("value too long for type character varying(60)")
        return len(records)

    monkeypatch.setattr("shared.data.bcrd_excel.engine.ingest_excel", fake_ingest)
    monkeypatch.setattr("shared.data.bcrd_excel.catalog.find_entry",
                        lambda fn: SimpleNamespace(url=f"http://x/{fn}", filename=fn, sector="s"))
    monkeypatch.setattr(service, "_upsert_records", fake_upsert)

    out = service.ingest_canonical(db, persist=True)

    # No propaga, procesa todos los archivos, y registra al menos un fallo.
    assert out["failed"] >= 1
    assert out["ok"] + out["flagged"] >= 1
    assert len(seen_files) >= 2  # no abortó tras el primer error
    # El reporte de fallo se escribió pese a la transacción envenenada.
    failed_rows = db.query(ExcelFileReport).filter_by(status="failed").count()
    assert failed_rows >= 1
