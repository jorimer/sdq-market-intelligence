"""El encabezado de años pegado a los datos NO deja fila de métricas.

Regresión de un defecto que se vio recién en la Data API, meses después: en
``Remesas_6.xlsx`` los años están en la fila 7 y Enero en la 8. La fórmula
``max(year_row+1, first_month_row-1)`` devolvía igual una fila de métricas, y caía sobre
la PRIMERA DE DATOS: cada columna quedaba bautizada con el valor de esa celda
(``remesas_6.280155040_6400002``). El archivo publica UNA magnitud; el extractor
inventaba 18 series con nombre de cifra.
"""
from shared.data.bcrd_excel.inference import infer_spec
from shared.data.bcrd_excel.workbook import Grid, Workbook


def _grid(rows, name="Total"):
    return Grid(name=name, rows=rows)


def _remesas_like():
    """Años en la fila 1, meses en la columna 0 desde la fila 2 — sin fila de métricas."""
    meses = ["Enero", "Febrero", "Marzo", "Abril", "Mayo", "Junio",
             "Julio", "Agosto", "Septiembre", "Octubre", "Noviembre", "Diciembre"]
    rows = [["REMESAS FAMILIARES", None, None, None, None, None]]
    rows.append(["PERIODOS", 2010, 2011, 2012, 2013, 2014])
    for i, m in enumerate(meses):
        rows.append([m] + [280155040.64 + i + 1000 * j for j in range(5)])
    return _grid(rows)


def test_no_metric_row_when_years_sit_right_above_the_data():
    spec = infer_spec(Workbook(path="test.xlsx", grids=[_remesas_like()]), "Remesas_6.xlsx")
    assert spec.orientation == "cross_tab"
    # Lo que importa: NO se toma la fila de datos como rótulos.
    assert spec.metric_header_row is None


def test_a_real_metric_row_is_still_detected():
    """El arreglo no debe cegar al extractor donde SÍ hay rótulos."""
    meses = ["Enero", "Febrero", "Marzo", "Abril", "Mayo", "Junio",
             "Julio", "Agosto", "Septiembre", "Octubre", "Noviembre", "Diciembre"]
    rows = [["RESERVAS", None, None, None, None, None],
            ["PERIODOS", 2010, 2011, 2012, 2013, 2014],
            [None, "Brutas", "Brutas", "Netas", "Netas", "Netas"]]
    for i, m in enumerate(meses):
        rows.append([m] + [100.0 + i + j for j in range(5)])
    spec = infer_spec(Workbook(path="test.xlsx", grids=[_grid(rows)]), "reservas.xlsx")
    assert spec.orientation == "cross_tab"
    assert spec.metric_header_row == 2       # la fila de rótulos, no la de datos


def test_a_numeric_candidate_row_is_never_taken_as_header():
    """Cinturón y tirantes: aunque la geometría deje lugar para una fila de métricas,
    una fila con mayoría de números son DATOS."""
    meses = ["Enero", "Febrero", "Marzo", "Abril", "Mayo", "Junio",
             "Julio", "Agosto", "Septiembre", "Octubre", "Noviembre", "Diciembre"]
    rows = [["X", None, None, None, None, None],
            ["PERIODOS", 2010, 2011, 2012, 2013, 2014],
            [None, 1.0, 2.0, 3.0, 4.0, 5.0]]      # fila numérica: NO es encabezado
    for i, m in enumerate(meses):
        rows.append([m] + [100.0 + i + j for j in range(5)])
    spec = infer_spec(Workbook(path="test.xlsx", grids=[_grid(rows)]), "raro.xlsx")
    assert spec.metric_header_row is None
