"""La sincronización poda lo que ella misma dejó de escribir — con cuatro frenos.

`ingest_canonical` hacía upsert y nunca podaba: cuando una corrección del extractor renombra
una serie, el código viejo se quedaba en `mm_series` sirviendo datos que ya nadie produce. No
fallaba, no avisaba, y hacía falta acordarse de limpiarlo a mano (365 series en producción el
2026-09-04). La cura durable es que la propia ingesta se lleve su arrastre, en la misma
corrida que lo genera.

Pero una poda automática es la operación más peligrosa que hay acá: se equivoca en silencio y
borra dato publicado. Por eso son cuatro frenos, y cada uno tapa una forma concreta de
destruir datos:

1. **Solo con `podar=True`.** El default no borra: quien enciende la poda lo declara.
2. **Solo archivos que se leyeron BIEN.** Un archivo que no se pudo descargar no autoriza a
   borrar sus series: la lectura vacía es del lado nuestro, no del emisor.
3. **Nunca desde un conjunto VACÍO.** Si un archivo se leyó «bien» y no produjo ninguna
   serie, eso es un bug, y tomarlo como verdad borraría el archivo entero.
4. **Tope proporcional.** Si la poda se llevaría más de la mitad de los códigos de un
   archivo, no se ejecuta y se REPORTA. Un renombrado masivo legítimo existe —pasó en esta
   misma rama— pero es un evento humano, no algo que una tarea mensual deba hacer sola.
"""
from types import SimpleNamespace

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from modules.macro_monitor import service
from modules.macro_monitor.models.models import ExcelFileReport, MacroSeries  # noqa: F401
from shared.data.base_client import Record
from shared.data.lineage import Lineage
from shared.database.base import Base

PREFIJO = "bcrd.xls.pib_2018"


@pytest.fixture()
def db():
    eng = create_engine("sqlite://", connect_args={"check_same_thread": False},
                        poolclass=StaticPool)
    Base.metadata.create_all(eng)
    s = sessionmaker(bind=eng)()
    yield s
    s.close()


def _lin():
    return Lineage(source="BCRD", license="público")


def _sembrar(db, codigos, periodos=("2020-Q1", "2020-Q2")):
    for c in codigos:
        for p in periodos:
            db.add(MacroSeries(series_code=c, period=p, value=1.0))
    db.commit()


def _correr(db, monkeypatch, escribe, *, podar=True, status="ok"):
    """Corre `ingest_canonical` con un motor falso que produce *escribe*."""
    def fake_ingest(entry, **kwargs):
        recs = [Record(series=c, period="2020-Q1", value=2.0, lineage=_lin())
                for c in escribe]
        report = SimpleNamespace(ok=status == "ok", series=[], flagged=[], avisos=[])
        spec = SimpleNamespace(method="heuristic", orientation="matrix",
                               frequency="quarterly", confidence=0.9)
        if status == "failed":
            raise RuntimeError("no se pudo descargar")
        return SimpleNamespace(records=recs, report=report, spec=spec)

    monkeypatch.setattr("shared.data.bcrd_excel.engine.ingest_excel", fake_ingest)
    monkeypatch.setattr("shared.data.bcrd_excel.catalog.find_entry",
                        lambda fn: SimpleNamespace(url=f"http://x/{fn}", filename=fn,
                                                   sector="s"))
    return service.ingest_canonical(db, persist=True, podar=podar,
                                    alcance={"pib_2018.xlsx": None})


def _codigos(db):
    return {r[0] for r in db.query(MacroSeries.series_code).distinct()}


def test_poda_el_codigo_que_dejo_de_producirse(db, monkeypatch):
    _sembrar(db, [f"{PREFIJO}.vieja", f"{PREFIJO}.se_queda"])
    out = _correr(db, monkeypatch, [f"{PREFIJO}.se_queda", f"{PREFIJO}.nueva"])
    assert f"{PREFIJO}.vieja" not in _codigos(db)
    assert {f"{PREFIJO}.se_queda", f"{PREFIJO}.nueva"} <= _codigos(db)
    assert out["pruned"] == 1


def test_sin_podar_no_borra_nada(db, monkeypatch):
    _sembrar(db, [f"{PREFIJO}.vieja"])
    out = _correr(db, monkeypatch, [f"{PREFIJO}.nueva"], podar=False)
    assert f"{PREFIJO}.vieja" in _codigos(db)
    assert out["pruned"] == 0


def test_un_archivo_que_no_se_pudo_leer_no_autoriza_a_borrar(db, monkeypatch):
    _sembrar(db, [f"{PREFIJO}.vieja"])
    out = _correr(db, monkeypatch, [], status="failed")
    assert f"{PREFIJO}.vieja" in _codigos(db), (
        "un archivo que falló borró sus series: la lectura vacía es nuestra, no del emisor")
    assert out["pruned"] == 0


def test_una_lectura_que_no_produjo_nada_tampoco(db, monkeypatch):
    _sembrar(db, [f"{PREFIJO}.vieja", f"{PREFIJO}.otra"])
    out = _correr(db, monkeypatch, [])
    assert {f"{PREFIJO}.vieja", f"{PREFIJO}.otra"} <= _codigos(db)
    assert out["pruned"] == 0


def test_el_tope_frena_una_poda_masiva_y_la_reporta(db, monkeypatch):
    viejas = [f"{PREFIJO}.v{i}" for i in range(10)]
    _sembrar(db, viejas)
    out = _correr(db, monkeypatch, [f"{PREFIJO}.unica_nueva"])
    assert set(viejas) <= _codigos(db), "una poda del 100% se ejecutó sola"
    assert out["pruned"] == 0
    assert out["prune_halted"], "la poda se frenó y no lo reportó"
    assert "pib_2018.xlsx" in out["prune_halted"][0]


def test_no_toca_series_de_otros_archivos(db, monkeypatch):
    _sembrar(db, [f"{PREFIJO}.vieja", "bcrd.xls.otro_archivo.serie", "fiscal_eo.ingresos"])
    _correr(db, monkeypatch, [f"{PREFIJO}.se_queda", f"{PREFIJO}.b", f"{PREFIJO}.c"])
    assert "bcrd.xls.otro_archivo.serie" in _codigos(db)
    assert "fiscal_eo.ingresos" in _codigos(db)


def test_reporta_los_codigos_y_las_observaciones_por_separado(db, monkeypatch):
    """Los códigos son lo que se decidió; las observaciones son el daño. Un informe que solo
    diga «1 podada» no deja saber si se fueron dos filas o dos mil."""
    _sembrar(db, [f"{PREFIJO}.vieja", f"{PREFIJO}.a", f"{PREFIJO}.b"],
             periodos=("2020-Q1", "2020-Q2", "2020-Q3"))
    out = _correr(db, monkeypatch, [f"{PREFIJO}.a", f"{PREFIJO}.b"])
    assert out["pruned"] == 1
    assert out["pruned_rows"] == 3
