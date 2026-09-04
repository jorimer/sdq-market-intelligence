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
    solo = {"pib_2018.xlsx": None, "imae_2018.xlsx": None}
    out = service.ingest_canonical(db, persist=True, alcance=solo)

    # se LEEN y se reportan todos los archivos del canónico...
    assert db.query(ExcelFileReport).count() == out["files"]
    assert out["files"] > len(solo)
    # ...y se ESCRIBEN solo los del alcance.
    escritos = {r.series_code for r in db.query(MacroSeries).all()}
    assert escritos == {"bcrd.xls.pib_2018.xlsx.s", "bcrd.xls.imae_2018.xlsx.s"}
    # lo omitido se DECLARA en el resultado, no desaparece
    assert set(out["skipped_by_scope"]) == {
        s.source_file for s in canonical.registry() if s.source_file not in solo}
    assert set(out["persist_scope"]) == set(solo)


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
    out = service.ingest_canonical(db, persist=False, alcance={"pib_2018.xlsx": None})
    assert db.query(MacroSeries).count() == 0
    assert db.query(ExcelFileReport).count() == out["files"]


def test_los_persistibles_verificados_existen_en_el_registro():
    """Un archivo habilitado que el canónico no declara no se ingeriría nunca: la lista
    quedaría 'encendida' sobre algo que ningún camino recorre."""
    archivos = {s.source_file for s in canonical.registry()}
    faltan = [f for f in canonical.PERSISTIBLES_VERIFICADOS if f not in archivos]
    assert not faltan, f"habilitados pero ausentes del REGISTRY: {faltan}"


def test_lo_habilitado_para_escribir_declara_ser_robusto():
    """«Es la fuente citable» y «ya se puede escribir sin degradar la base» son dos
    afirmaciones distintas, y la segunda no puede contradecir a la primera.

    La regla es POR HOJA porque el alcance lo es: un archivo habilitado ENTERO (valor `None`)
    tiene que declararse `green`; uno habilitado por HOJAS puede ser `yellow` —eso es
    justamente lo que `yellow` dice: parte del libro no extrae limpio— siempre que nombre
    cuáles. Lo que no se admite es habilitar entero algo que el propio registro marca como no
    confiable, ni «habilitar por hojas» con la lista vacía, que sería habilitar nada y
    parecer que se habilitó algo."""
    por_archivo = {}
    for s in canonical.registry():
        por_archivo.setdefault(s.source_file, []).append(s.robustness)
    enteros_no_green, hojas_vacias = [], []
    for archivo, hojas in canonical.PERSISTIBLES_VERIFICADOS.items():
        robusteces = por_archivo.get(archivo, [])
        if hojas is None:
            if any(r != "green" for r in robusteces):
                enteros_no_green.append(archivo)
        elif not hojas:
            hojas_vacias.append(archivo)
    assert not enteros_no_green, (
        f"habilitados ENTEROS pese a no ser 'green': {enteros_no_green}. Si solo algunas "
        f"hojas extraen limpio, habilitá esas hojas en vez del archivo.")
    assert not hojas_vacias, f"habilitados 'por hojas' con la lista vacía: {hojas_vacias}"


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


# ── Alcance por HOJA ─────────────────────────────────────────────────────────────
#
# Un libro puede traer hojas que extraen bien y hojas que no. El PIB por sector de origen es
# el caso: sus dos hojas trimestrales salen limpias y las dos ACUMULADAS mezclan períodos
# anuales y trimestrales en la misma serie, con 1.660 duplicados de valores distintos. Como la
# ingesta es por archivo, sin alcance por hoja el libro entero se quedaba afuera.


def _fake_multihoja(entry, **kw):
    """Un libro de dos hojas cuyos slugs son uno PREFIJO del otro — la trampa real."""
    lin = Lineage(source="BCRD", license="x", fetched_at=date.today())
    recs, series = [], []
    for hoja in ("pib_trim", "pib_trim_acum"):
        code = f"bcrd.xls.pib_origen_2018.{hoja}.agropecuario"
        recs.append(Record(series=code, period="2020-Q1", value=1.0, lineage=lin))
        series.append(SimpleNamespace(code=code, flags=[]))
    spec = SimpleNamespace(method="heuristic", orientation="matrix",
                           frequency="quarterly", confidence=0.8)
    return SimpleNamespace(file=entry.filename, spec=spec, records=recs,
                           report=SimpleNamespace(ok=True, series=series, flagged=[]))


def test_habilitar_una_hoja_no_arrastra_la_que_la_tiene_de_PREFIJO(db, monkeypatch):
    """`pib_trim` es prefijo de `pib_trim_acum`. Sin el punto final en el prefijo del filtro,
    habilitar la hoja limpia metería la rota — que es exactamente lo que este alcance existe
    para impedir."""
    monkeypatch.setattr("shared.data.bcrd_excel.engine.ingest_excel", _fake_multihoja)
    monkeypatch.setattr("shared.data.bcrd_excel.catalog.find_entry",
                        lambda fn: SimpleNamespace(url=f"http://x/{fn}", filename=fn, sector="s"))
    service.ingest_canonical(db, persist=True,
                             alcance={"pib_origen_2018.xlsx": ["PIB$_Trim"]})
    escritos = {r.series_code for r in db.query(MacroSeries).all()}
    assert escritos == {"bcrd.xls.pib_origen_2018.pib_trim.agropecuario"}


def test_declarar_una_hoja_que_no_produce_nada_FALLA_ruidosamente(db, monkeypatch):
    """Escribir cero en silencio se lee, meses después, como que la fuente dejó de traer
    datos. Un nombre de hoja mal escrito —o un libro de UNA hoja, donde el código no lleva
    segmento de hoja— tiene que quedar registrado como fallo del archivo."""
    monkeypatch.setattr("shared.data.bcrd_excel.engine.ingest_excel", _fake_multihoja)
    monkeypatch.setattr("shared.data.bcrd_excel.catalog.find_entry",
                        lambda fn: SimpleNamespace(url=f"http://x/{fn}", filename=fn, sector="s"))
    out = service.ingest_canonical(db, persist=True,
                                   alcance={"pib_origen_2018.xlsx": ["Hoja Que No Existe"]})
    assert db.query(MacroSeries).count() == 0
    assert out["failed"] >= 1
    fallo = db.query(ExcelFileReport).filter_by(status="failed").first()
    assert fallo is not None and "alcance" in (fallo.error or "").lower()


def test_las_hojas_habilitadas_del_pib_sectorial_se_nombran_una_por_una():
    """Las cuatro hojas están habilitadas, y se LISTAN en vez de poner `None`.

    El valor es el mismo hoy —las cuatro extraen limpias tras corregir los rótulos del cuadro
    acumulado— pero la lista dice cuáles se verificaron una por una. Si el BCRD agrega una
    quinta hoja, no se habilita sola: alguien tiene que mirarla. `None` la habilitaría en
    silencio, que es como entró el problema que esto vino a cerrar."""
    hojas = canonical.PERSISTIBLES_VERIFICADOS["pib_origen_2018.xlsx"]
    assert hojas is not None, "con `None`, una hoja nueva del emisor se habilitaría sola"
    assert set(hojas) == {"PIB$_Trim", "PIBK_Trim", "PIB$_Trim_Acum", "PIBK_Trim_Acum"}
