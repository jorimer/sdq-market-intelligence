"""Un nombre ya congelado gana, aunque el modelo diga otra cosa.

El `series_code` que sale del nombrado semántico es un CONTRATO: se persiste, se cita y la
Data API se lo sirve a PMS. Mientras el mapa de nombres vivió solo en `data/` —gitignored, y
en Railway el filesystem del contenedor, que cada deploy borra— al modelo se le volvía a
preguntar y reformulaba el mismo encabezado. Medido en producción el 2026-09-04, en una sola
corrida:

    pibk_trim.indice_de_volumen_por_actividad_economica.*  →  pibk_trim.indices_de_volumen_encadenados.*
    lleg_total…total.no_residentes.dominicanos             →  lleg_total…volumen.no_residentes.dominicanos

**40 de 2.103 series cambiaron de código.** Ningún dato se perdió —los valores se reescriben
bajo el nombre nuevo y la poda se lleva el viejo, que es lo que debe hacer— pero un consumidor
que guardó el código no encuentra nada.

Congelado en el paquete, el nombre se decide UNA vez y se revisa como código. Lo que este
test fija es la PRECEDENCIA: el congelado gana. Si ganara el del modelo, congelarlo no
serviría de nada.
"""
import json
from pathlib import Path

from shared.data.bcrd_excel import engine
from shared.data.base_client import Record
from shared.data.lineage import Lineage
from shared.data.bcrd_excel.spec import ExtractionSpec
from shared.data.bcrd_excel.workbook import Grid, Workbook

CONGELADOS = json.loads(
    (Path(engine.__file__).parent / "nombres_semanticos.json").read_text(encoding="utf-8"))


def test_el_archivo_congelado_existe_y_no_esta_vacio():
    assert CONGELADOS["nombres"], "el mapa congelado quedó vacío"
    filas = sum(len(v) for v in CONGELADOS["nombres"].values())
    assert filas >= 300, f"solo {filas} filas congeladas: ¿se regeneró contra una caché a medias?"


def test_declara_por_que_esta_comiteado():
    assert len(CONGELADOS.get("_por_que_esta_comiteado", "")) > 100


class _CacheFalsa:
    def __init__(self, names):
        self.names = names
        self.guardado = None

    def get_names(self, key):
        return dict(self.names)

    def set_names(self, key, value):
        self.guardado = value


def _wb():
    return Workbook(path=None, grids=[Grid(name="h", rows=[["a"], ["b"]])])


def _spec():
    return ExtractionSpec(file="f.xls", sheet="h", orientation="matrix", data_row_start=0,
                          code_prefix="p")


def _recs():
    lin = Lineage(source="BCRD", license="público")
    return [Record(series="p.fila_r17", period="2010", value=1.0, lineage=lin)]


def test_el_nombre_congelado_le_gana_al_del_modelo(monkeypatch):
    monkeypatch.setattr(engine, "_nombres_congelados",
                        lambda _h: {17: "Importaciones > Nacionales"})

    def jamas(grid, rows, client=None):
        raise AssertionError("no debería preguntarle al modelo por una fila congelada")

    monkeypatch.setattr(engine, "name_ambiguous_rows", jamas)
    cache = _CacheFalsa({"17": "Otra Cosa > Que El Modelo Dijo Esta Vez"})
    out = engine._resolve_ambiguous_names(_wb(), _spec(), _recs(), cache=cache)
    assert {r.series for r in out} == {"p.importaciones.nacionales"}


def test_una_fila_nueva_si_se_le_pregunta_al_modelo(monkeypatch):
    monkeypatch.setattr(engine, "_nombres_congelados", lambda _h: {})
    monkeypatch.setattr(engine, "name_ambiguous_rows",
                        lambda grid, rows, client=None: {17: "Algo > Nuevo"})
    cache = _CacheFalsa({})
    out = engine._resolve_ambiguous_names(_wb(), _spec(), _recs(), cache=cache)
    assert {r.series for r in out} == {"p.algo.nuevo"}
