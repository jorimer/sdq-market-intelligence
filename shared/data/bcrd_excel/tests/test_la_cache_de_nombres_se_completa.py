"""La caché de nombres es PARCIAL: si aparecen filas nuevas, se piden solo esas.

El nombrado semántico se cachea por hash de estructura para pagarlo una vez por layout. Pero
la lectura era todo-o-nada: si había ENTRADA en la caché, se usaba tal cual y las filas que
no estuvieran en ella se quedaban con su coordenada (`_rNN`) para siempre — sin error, sin
aviso, y vetadas en la frontera de escritura por no nombrar su sujeto.

Salta en cuanto cambia qué filas se consideran ambiguas: al desempatar también la PRIMERA
aparición de un rótulo repetido, 140 filas del corpus pasaron a serlo y ninguna se nombró,
porque su archivo ya tenía caché.

La caché sigue evitando el gasto —solo se piden las filas que faltan— y lo pedido se fusiona
con lo guardado.
"""
from types import SimpleNamespace

from shared.data.bcrd_excel import engine
from shared.data.base_client import Record
from shared.data.lineage import Lineage
from shared.data.bcrd_excel.spec import ExtractionSpec
from shared.data.bcrd_excel.workbook import Grid, Workbook


class _Cache:
    def __init__(self, names):
        self.names = names
        self.guardado = None

    def get_names(self, key):
        return dict(self.names)

    def set_names(self, key, value):
        self.guardado = value


def _wb():
    return Workbook(path=None, grids=[Grid(name="h", rows=[["a"], ["b"], ["c"]])])


def _recs():
    lin = Lineage(source="BCRD", license="público")
    return [Record(series=f"p.nacionales_r{r}", period="2010", value=1.0, lineage=lin)
            for r in (14, 17)]


def _spec():
    return ExtractionSpec(file="f.xls", sheet="h", orientation="matrix", data_row_start=0, code_prefix="p")


def test_pide_solo_las_filas_que_faltan(monkeypatch):
    pedidas = {}

    def fake(grid, rows, client=None):
        pedidas["rows"] = list(rows)
        return {17: "Importaciones > Nacionales"}

    monkeypatch.setattr(engine, "name_ambiguous_rows", fake)
    cache = _Cache({"14": "Exportaciones > Nacionales"})
    out = engine._resolve_ambiguous_names(_wb(), _spec(), _recs(), cache=cache)
    assert pedidas["rows"] == [17], f"pidió {pedidas.get('rows')} en vez de solo la 17"
    codigos = sorted({r.series for r in out})
    assert codigos == ["p.exportaciones.nacionales", "p.importaciones.nacionales"], codigos
    assert cache.guardado == {"14": "Exportaciones > Nacionales",
                              "17": "Importaciones > Nacionales"}


def test_si_la_cache_las_tiene_todas_no_pregunta(monkeypatch):
    def fake(grid, rows, client=None):
        raise AssertionError("no debería preguntar")

    monkeypatch.setattr(engine, "name_ambiguous_rows", fake)
    cache = _Cache({"14": "Exportaciones > Nacionales", "17": "Importaciones > Nacionales"})
    out = engine._resolve_ambiguous_names(_wb(), _spec(), _recs(), cache=cache)
    assert len({r.series for r in out}) == 2
