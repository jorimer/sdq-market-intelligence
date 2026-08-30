"""Un rótulo PARTIDO en dos filas no colapsa doce series en una.

El caso. El IPC por grupos del BCRD apila los años en filas sueltas (`year_blocks`) y pone
los doce grupos de la canasta en columnas alternas de Índice y Var. %. El nombre del grupo
se ENVUELVE en dos filas —«Bebidas Alcohólicas y Tabaco» arriba, «y Tabaco» abajo— porque
Excel ajusta el texto de una celda ancha.

La inferencia tomaba como super-encabezado la PENÚLTIMA fila del bloque, que en ese layout
es la continuación del rótulo, no el rótulo. Resultado: las doce columnas de índice salían
con el mismo nombre y colapsaban en UNA serie con doce valores por mes, la última pisando a
las anteriores. No fallaba nada: el archivo se ingería y quedaba una serie sin sentido.

El arreglo tiene dos mitades y ambas hacen falta: la inferencia apunta a la PRIMERA fila del
bloque, y el extractor UNE desde ahí hasta la métrica, saltando las partes ya contenidas
—«Bebidas Alcohólicas y Tabaco» + «y Tabaco» no es «…y Tabaco y Tabaco»—.
"""

from shared.data.bcrd_excel.extract import _extract_year_blocks
from shared.data.bcrd_excel.spec import ExtractionSpec


class _Grid:
    name = "hoja"

    def __init__(self, celdas, nrows=12, ncols=6):
        self._c, self.nrows, self.ncols = celdas, nrows, ncols

    def cell(self, r, c):
        return self._c.get((r, c))


def _spec(**kw):
    base = dict(file="f.xls", sheet="hoja", orientation="year_blocks", data_row_start=4,
                month_col=0, super_header_row=1, metric_header_row=3,
                value_col_start=1, value_col_end=5)
    base.update(kw)
    return ExtractionSpec(**base)


def _grid_dos_grupos():
    return _Grid({
        # fila 1: rótulos del grupo (el segundo, envuelto) · fila 2: su continuación
        (1, 1): "Alimentos", (1, 3): "Bebidas Alcohólicas y Tabaco",
        (2, 3): "y Tabaco",
        # fila 3: la métrica, alternando
        (3, 1): "Indice", (3, 2): "Var. %", (3, 3): "Indice", (3, 4): "Var. %",
        # bloque de año y un mes
        (4, 0): 2024, (5, 0): "Enero",
        (5, 1): 100.0, (5, 2): 1.0, (5, 3): 200.0, (5, 4): 2.0,
    })


def _hoja_ipc_grupos():
    """Réplica mínima del layout real: años en fila suelta, rótulo envuelto en dos filas."""
    c = {
        (1, 1): "Alimentos", (1, 3): "Bebidas Alcohólicas y Tabaco",
        (2, 3): "y Tabaco",                      # continuación del rótulo envuelto
        (3, 1): "Indice", (3, 2): "Var. %", (3, 3): "Indice", (3, 4): "Var. %",
    }
    MESES = ("Enero", "Febrero", "Marzo", "Abril", "Mayo", "Junio", "Julio", "Agosto",
             "Septiembre", "Octubre", "Noviembre", "Diciembre")
    r = 4
    for anio in (2022, 2023, 2024):              # tres bloques: el mínimo de la heurística
        c[(r, 0)] = anio
        r += 1
        for m in MESES:
            c[(r, 0)] = m
            c[(r, 1)], c[(r, 2)], c[(r, 3)], c[(r, 4)] = 100.0, 1.0, 200.0, 2.0
            r += 1
    return _Grid(c, nrows=r, ncols=6)


class _Wb:
    """Workbook mínimo: `grids` es lo que la inferencia recorre para elegir la hoja."""

    def __init__(self, grid):
        self._g = grid
        self.grids = [grid]

    def grid(self, _name=None):
        return self._g

    def structure_hash(self):
        return "test"


def test_la_inferencia_apunta_a_la_PRIMERA_fila_del_encabezado():
    """La penúltima es la CONTINUACIÓN del rótulo, no el rótulo."""
    from shared.data.bcrd_excel.inference import infer_spec
    sp = infer_spec(_Wb(_hoja_ipc_grupos()), "ipc_grupos.xls")
    assert sp.orientation == "year_blocks"
    assert sp.super_header_row == 1, (
        f"apunta a la fila {sp.super_header_row}: si es la continuación del rótulo, las "
        f"columnas de índice salen con el mismo nombre y colapsan en una sola serie")


def test_de_punta_a_punta_cada_grupo_conserva_su_serie():
    """El defecto no fallaba: el archivo se ingería y quedaba UNA serie con doce valores
    por mes, la última pisando a las anteriores."""
    from shared.data.bcrd_excel.inference import infer_spec
    from shared.data.bcrd_excel.extract import extract_records

    wb = _Wb(_hoja_ipc_grupos())
    recs = extract_records(wb, infer_spec(wb, "ipc_grupos.xls"))
    indices = {r.series for r in recs if r.series.endswith("_indice")}
    assert len(indices) == 2, f"colapsaron: {indices}"
    valores = {r.series: r.value for r in recs}
    assert valores[[s for s in indices if "alimentos" in s][0]] == 100.0
    assert valores[[s for s in indices if "tabaco" in s][0]] == 200.0


def test_cada_grupo_conserva_su_propia_serie():
    recs = _extract_year_blocks(_grid_dos_grupos(), _spec(), lineage=None, prefix="p")
    codigos = {r.series for r in recs}
    assert len(codigos) == 4, f"colapsaron series: {codigos}"
    assert "p.alimentos_indice" in codigos
    assert "p.bebidas_alcoholicas_y_tabaco_indice" in codigos


def test_el_rotulo_envuelto_no_se_DUPLICA():
    """«Bebidas Alcohólicas y Tabaco» + «y Tabaco» no es «…y_tabaco_y_tabaco»."""
    recs = _extract_year_blocks(_grid_dos_grupos(), _spec(), lineage=None, prefix="p")
    assert not [r for r in recs if r.series.count("tabaco") > 1]


def test_los_valores_van_a_la_serie_que_les_corresponde():
    """Si el nombre colapsa, los 200 del segundo grupo pisan los 100 del primero."""
    recs = {r.series: r.value for r in
            _extract_year_blocks(_grid_dos_grupos(), _spec(), lineage=None, prefix="p")}
    assert recs["p.alimentos_indice"] == 100.0
    assert recs["p.bebidas_alcoholicas_y_tabaco_indice"] == 200.0


def test_sin_super_encabezado_sigue_nombrando_por_la_metrica():
    """No se rompe el layout de una sola métrica, que es para el que se escribió."""
    g = _Grid({(3, 1): "Total", (4, 0): 2024, (5, 0): "Enero", (5, 1): 7.0})
    recs = _extract_year_blocks(g, _spec(super_header_row=None), lineage=None, prefix="p")
    assert [r.series for r in recs] == ["p.total"]
