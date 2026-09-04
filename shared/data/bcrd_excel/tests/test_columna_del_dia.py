"""Cuando la planilla trae `Año | Mes | Día`, el DÍA es período — no una serie.

El tipo de cambio publica su corte diario así, y el motor lo leía como una columna de valores
más: nacía una serie `...diaria.dia` cuyos «valores» eran 2, 3, 4, 7, 8, 9 —los días del
calendario— mientras las tres columnas reales colapsaban en `YYYY-MM`, una observación por
mes elegida por orden de lectura. 19.680 valores en conflicto en un solo archivo.

Lo decide el ENCABEZADO, que es donde el emisor lo declara.
"""
import pytest

from shared.data.bcrd_excel.extract import extract_records
from shared.data.bcrd_excel.inference import infer_spec
from shared.data.bcrd_excel.workbook import Grid, Workbook


def _hoja(encabezado):
    filas = [["Tasas de Cambio"], [], encabezado]
    dia = 1
    for anio in (1991, 1992):
        for mes in ("Ene", "Feb", "Mar", "Abr", "May", "Jun",
                    "Jul", "Ago", "Sep", "Oct", "Nov", "Dic"):
            for d in (2, 3, 4):
                filas.append([anio, mes, d, 11.0 + dia * 0.01, 11.5 + dia * 0.01])
                dia += 1
    return Workbook(path=None, grids=[Grid(name="Diaria", rows=filas)])


def _spec(wb):
    return infer_spec(wb, "TASA_DOLAR_REFERENCIA_MC.xlsx")


def test_la_columna_del_dia_se_reconoce_como_periodo():
    sp = _spec(_hoja(["Año", "Mes", "Día", "Compra", "Venta"]))
    assert sp.day_col == 2, f"day_col={sp.day_col}"


def test_el_dia_NO_se_persiste_como_una_serie():
    wb = _hoja(["Año", "Mes", "Día", "Compra", "Venta"])
    sp = _spec(wb)
    codigos = {s.code for s in sp.series}
    assert "dia" not in codigos, codigos
    assert {"compra", "venta"} <= codigos, codigos


def test_los_dias_de_un_mes_ya_no_colapsan():
    wb = _hoja(["Año", "Mes", "Día", "Compra", "Venta"])
    sp = _spec(wb)
    sp.code_prefix = "p"
    recs = extract_records(wb, sp)
    compra = [r for r in recs if r.series.endswith(".compra")]
    periodos = sorted(str(r.period) for r in compra)
    assert len(periodos) == len(set(periodos)), "hay períodos repetidos: siguen colapsando"
    assert periodos[0] == "1991-01-02"
    assert all(len(p) == 10 for p in periodos)


def test_sin_columna_de_dia_nada_cambia():
    """Una planilla mensual normal no gana un `day_col` por accidente."""
    wb = _hoja(["Año", "Mes", "Compra", "Venta"])
    # sin la columna de día, la tercera es un valor más
    sp = _spec(wb)
    assert sp.day_col is None
