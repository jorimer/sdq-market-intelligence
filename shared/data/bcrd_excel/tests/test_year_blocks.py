"""Bloques apilados por año: el año en fila suelta, sus meses debajo.

Layout real del BCRD (llegada de pasajeros, 1978-2026): ``1978`` solo en su fila, los
doce meses debajo, y las métricas a lo ancho. Caía en ``matrix`` y cada mes repetido se
volvía una serie —`enero`, `enero_r35`, `enero_r48`—: no era un problema de NOMBRE sino
de FORMA. Los meses son períodos, no series.
"""
from shared.data.bcrd_excel.extract import extract_records
from shared.data.bcrd_excel.inference import infer_spec
from shared.data.bcrd_excel.workbook import Grid, Workbook

_MESES = ["Enero", "Febrero", "Marzo", "Abril", "Mayo", "Junio",
          "Julio", "Agosto", "Septiembre", "Octubre", "Noviembre", "Diciembre"]


def _wb(años=(1978, 1979, 1980)):
    rows = [["LLEGADA DE PASAJEROS", None, None],
            ["Período", "Total", None],
            [None, "Mensual", "Acumulado"]]
    for a in años:
        rows.append([a, None, None])                    # cabecera de bloque
        for i, m in enumerate(_MESES):
            rows.append([m, 100.0 + i, 1000.0 + i])
    return Workbook(path="lleg.xls", grids=[Grid(name="No Residentes", rows=rows)])


def test_the_layout_is_detected():
    spec = infer_spec(_wb(), "lleg_total.xls")
    assert spec.orientation == "year_blocks"


def test_months_become_periods_not_series():
    spec = infer_spec(_wb(), "lleg_total.xls")
    recs = extract_records(_wb(), spec)
    codes = {r.series.split(".")[-1] for r in recs}
    assert not any(c.startswith("enero") for c in codes)   # ningún mes es serie
    assert "total_mensual" in codes and "total_acumulado" in codes


def test_the_period_combines_the_block_year_with_the_row_month():
    spec = infer_spec(_wb(), "lleg_total.xls")
    recs = extract_records(_wb(), spec)
    periods = sorted({r.period for r in recs})
    assert periods[0] == "1978-01" and periods[-1] == "1980-12"
    assert len(periods) == 36           # 3 años × 12 meses, sin repetir


def test_values_land_under_the_right_year():
    spec = infer_spec(_wb(), "lleg_total.xls")
    recs = extract_records(_wb(), spec)
    ene79 = [r for r in recs if r.period == "1979-01" and r.series.endswith("total_mensual")]
    assert len(ene79) == 1 and ene79[0].value == 100.0


def test_a_sheet_without_standalone_years_is_not_year_blocks():
    """No debe capturar layouts que ya resuelven bien otras orientaciones."""
    rows = [["PERIODOS", 2010, 2011, 2012, 2013]]
    for i, m in enumerate(_MESES):
        rows.append([m] + [1.0 + i + j for j in range(4)])
    spec = infer_spec(Workbook(path="x.xls", grids=[Grid(name="H", rows=rows)]), "x.xls")
    assert spec.orientation != "year_blocks"
