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


# ── Alcance de ESCRITURA del canónico (encendido acotado, 2026-09-03) ─────────────
#
# `PERSISTIBLES_VERIFICADOS` es una lista TRANSITORIA: los archivos que la corrida en seco
# verificó como escribibles sin degradar la base. Lo que estos tests fijan no es su
# contenido —va a crecer— sino su SEMÁNTICA: acota lo que se escribe, nunca lo que se lee.
# Perder el reporte de los 26 dejaría sin instrumento la decisión de qué habilitar después.


def _fake_ingest_por_archivo(entry, **kw):
    """Un registro por archivo, con el nombre del archivo en el código de la serie."""
    lin = Lineage(source="BCRD", license="x", fetched_at=date.today())
    code = f"bcrd.xls.{entry.filename}.s"
    report = SimpleNamespace(ok=True, series=[SimpleNamespace(code=code, flags=[])], flagged=[])
    spec = SimpleNamespace(method="heuristic", orientation="period_rows",
                           frequency="annual", confidence=0.8)
    return SimpleNamespace(file=entry.filename, spec=spec,
                           records=[Record(series=code, period="2020", value=1.0, lineage=lin)],
                           report=report)


def test_el_alcance_acota_lo_que_se_escribe_pero_no_lo_que_se_lee(db, monkeypatch):
    monkeypatch.setattr("shared.data.bcrd_excel.engine.ingest_excel", _fake_ingest_por_archivo)
    solo = ["pib_2018.xlsx", "imae_2018.xlsx"]
    out = service.ingest_canonical(db, persist=True, solo_archivos=solo)

    # se LEEN y se reportan todos los archivos del canónico...
    assert db.query(ExcelFileReport).count() == out["files"]
    assert out["files"] > len(solo)
    # ...y se ESCRIBEN solo los del alcance.
    escritos = {r.series_code for r in db.query(MacroSeries).all()}
    assert escritos == {"bcrd.xls.pib_2018.xlsx.s", "bcrd.xls.imae_2018.xlsx.s"}
    # lo omitido se DECLARA en el resultado, no desaparece
    assert set(out["skipped_by_scope"]) == {
        s.source_file for s in canonical.registry() if s.source_file not in solo}
    assert out["persist_scope"] == sorted(solo)


def test_sin_alcance_se_escribe_todo_el_canonico(db, monkeypatch):
    """El default `None` conserva el comportamiento histórico: quien no pide alcance,
    no lo recibe por sorpresa."""
    monkeypatch.setattr("shared.data.bcrd_excel.engine.ingest_excel", _fake_ingest_por_archivo)
    out = service.ingest_canonical(db, persist=True)
    assert db.query(MacroSeries).count() == out["files"]
    assert out["skipped_by_scope"] == []
    assert out["persist_scope"] == "todos"


def test_el_alcance_no_escribe_nada_sin_persist(db, monkeypatch):
    """`solo_archivos` acota la escritura; no la habilita. Sin `persist` no se escribe nada,
    y el reporte de cobertura sigue saliendo completo."""
    monkeypatch.setattr("shared.data.bcrd_excel.engine.ingest_excel", _fake_ingest_por_archivo)
    out = service.ingest_canonical(db, persist=False, solo_archivos=["pib_2018.xlsx"])
    assert db.query(MacroSeries).count() == 0
    assert db.query(ExcelFileReport).count() == out["files"]


def test_los_persistibles_verificados_existen_en_el_registro():
    """Un archivo habilitado que el canónico no declara no se ingeriría nunca: la lista
    quedaría 'encendida' sobre algo que ningún camino recorre."""
    archivos = {s.source_file for s in canonical.registry()}
    faltan = [f for f in canonical.PERSISTIBLES_VERIFICADOS if f not in archivos]
    assert not faltan, f"habilitados pero ausentes del REGISTRY: {faltan}"


def test_lo_habilitado_para_escribir_declara_ser_robusto():
    """Un archivo no entra a `PERSISTIBLES_VERIFICADOS` si su propia entrada del registro
    dice que no extrae limpio. Son dos afirmaciones distintas —«es la fuente citable» y
    «ya se puede escribir sin degradar la base»— y la segunda no puede contradecir a la
    primera. El PIB por origen es el caso: entra al registro en `yellow` porque dos de sus
    cuatro hojas mezclan períodos anuales y trimestrales, y por eso NO se habilita."""
    por_archivo = {}
    for s in canonical.registry():
        por_archivo.setdefault(s.source_file, []).append(s.robustness)
    malos = [f for f in canonical.PERSISTIBLES_VERIFICADOS
             if any(r != "green" for r in por_archivo.get(f, []))]
    assert not malos, f"habilitados para escribir pese a no ser 'green': {malos}"


def test_el_pib_sectorial_apunta_al_archivo_VIGENTE_no_al_congelado():
    """`PIB_sectores_origen.xls` es el que el nombre sugiere y el que el spec señalaba, pero
    está congelado desde 2019-02-23 y termina en 2014, en la base vieja. El vigente es
    `pib_origen_2018.xlsx`. Es la misma trampa del IMAE, y por eso se fija igual que aquélla."""
    s = canonical.by_key("pib_sectores_origen")
    assert s is not None, "el registro no declara el PIB por sector de origen"
    assert s.source_file == "pib_origen_2018.xlsx"
    assert s.frequency == "trimestral"
    assert find_entry(s.source_file) is not None
    congelados = {"PIB_sectores_origen.xls", "imae.xlsx"}
    usados = {x.source_file for x in canonical.registry()}
    assert not (usados & congelados), f"el registro apunta a archivos congelados: {usados & congelados}"
