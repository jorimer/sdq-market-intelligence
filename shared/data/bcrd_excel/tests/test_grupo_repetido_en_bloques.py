"""Un rótulo de grupo que se REPITE en la fila no identifica a nadie — ni al primero.

En las llegadas de pasajeros el encabezado tiene dos niveles: `Total | Tasa de Crecimiento |
Dominicanos | Tasa de Crecimiento`, y debajo `Mensual | Acumulado | Trimestral | Igual Mes…`.
«Tasa de Crecimiento» aparece bajo *Total* y bajo *Dominicanos*: las dos columnas producían el
MISMO código y colisionaban en silencio — 4.555 valores en conflicto, resueltos por orden de
lectura.

Es la doctrina del sujeto en la orientación que todavía no la aplicaba: `period_rows` ya
califica un nombre repetido con el grupo de al lado (`_grupo_a_la_izquierda`), `year_blocks`
no. Y la regla es la misma que allá: se califica a TODOS los que comparten el rótulo, no solo
a los que llegan después — el primero tampoco queda identificado por «Tasa de Crecimiento» a
secas.
"""
from shared.data.bcrd_excel.extract import extract_records
from shared.data.bcrd_excel.spec import ExtractionSpec
from shared.data.bcrd_excel.workbook import Grid, Workbook

_METRICAS = ["Mensual", "Acumulado", "Trimestral"]
_TASAS = ["Igual Mes", "Acumulado", "Trimestral"]


def _grid():
    ancho = 13
    r_super = [None] * ancho
    r_metr = [None] * ancho
    r_super[1] = "Total"
    r_super[4] = "Tasa de Crecimiento"
    r_super[7] = "Dominicanos"
    r_super[10] = "Tasa de Crecimiento"
    for i, m in enumerate(_METRICAS):
        r_metr[1 + i] = m
        r_metr[7 + i] = m
    for i, m in enumerate(_TASAS):
        r_metr[4 + i] = m
        r_metr[10 + i] = m
    filas = [["LLEGADA TOTAL DE PASAJEROS"], ["No Residentes"], r_super, r_metr]
    v = 100.0
    for anio in (1978, 1979):
        filas.append([float(anio)] + [None] * (ancho - 1))
        for mes in ("Enero", "Febrero", "Marzo"):
            fila = [mes] + [None] * (ancho - 1)
            for c in range(1, ancho):
                fila[c] = v
                v += 1
            filas.append(fila)
    return Workbook(path=None, grids=[Grid(name="No Residentes 78 - 26", rows=filas)])


def _spec():
    return ExtractionSpec(
        file="lleg_total.xls", sheet="No Residentes 78 - 26", orientation="year_blocks",
        data_row_start=4, month_col=0, super_header_row=2, metric_header_row=3,
        value_col_start=1, value_col_end=13, code_prefix="p",
    )


def _codigos():
    return {r.series for r in extract_records(_grid(), _spec())}


def test_las_doce_columnas_dan_doce_series():
    """Cuatro grupos por tres métricas. Si salen menos, dos columnas se fusionaron."""
    assert len(_codigos()) == 12, sorted(_codigos())


def test_las_dos_tasas_de_crecimiento_se_distinguen():
    cods = _codigos()
    assert any(c.endswith("total_tasa_de_crecimiento_igual_mes") for c in cods), sorted(cods)
    assert any(c.endswith("dominicanos_tasa_de_crecimiento_igual_mes") for c in cods), sorted(cods)


def test_ningun_periodo_se_repite_dentro_de_una_serie():
    """La prueba de que ya no colisionan: con 12 series y 6 meses son 72 pares únicos."""
    recs = extract_records(_grid(), _spec())
    claves = [(r.series, r.period) for r in recs]
    assert len(claves) == len(set(claves)), "hay (serie, período) repetidos"
    assert len(claves) == 12 * 6


def test_un_grupo_UNICO_no_se_ensucia():
    """`Total` y `Dominicanos` aparecen una sola vez: no necesitan calificarse, y meterles
    un ancestro les cambiaría el nombre sin motivo."""
    cods = _codigos()
    assert any(c.endswith(".total_mensual") for c in cods), sorted(cods)
    assert any(c.endswith(".dominicanos_mensual") for c in cods), sorted(cods)
