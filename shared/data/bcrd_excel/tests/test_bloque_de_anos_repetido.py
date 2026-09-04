"""Cuando el eje de años REINICIA, empieza otro bloque — y su título va en el código.

La hoja «1993 - 2026» de las llegadas de pasajeros trae DOS cuadros lado a lado, separados
por una columna vacía: los años completos 1993-2025 y, con su propio título una fila más
arriba, «enero-julio 2023-2026» — un corte acumulado. Los años 2023, 2024 y 2025 aparecen en
los dos con valores distintos (9.009.094 el año completo, 5.408.034 el corte), y como el
código de la serie no decía a qué bloque pertenecía, competían por la misma clave: tres
valores en conflicto por serie, resueltos por orden de lectura.

Es la doctrina del sujeto una vez más: el segundo bloque mide otra cosa y tiene que decirlo.
El PRIMERO no se califica —es el cuadro principal y su título («AÑOS») no aporta nada—; lo
que se nombra es lo que se aparta de él.
"""
from shared.data.bcrd_excel.extract import extract_records
from shared.data.bcrd_excel.spec import ExtractionSpec
from shared.data.bcrd_excel.workbook import Grid, Workbook


def _grid(titulo="enero-julio 2024-2025"):
    #      c0        c1    c2    c3    c4   c5    c6
    r_tit = ["AÑOS", None, None, None, None, titulo, None]
    r_year = ["DETALLE", 2023, 2024, 2025, None, 2024, 2025]
    fila1 = ["TOTAL", 10.0, 20.0, 30.0, None, 11.0, 12.0]
    fila2 = ["RESIDENTES", 40.0, 50.0, 60.0, None, 13.0, 14.0]
    return Workbook(path=None, grids=[Grid(name="1993 - 2026",
                                           rows=[["LLEGADA"], [], r_tit, r_year, fila1, fila2])])


def _spec():
    return ExtractionSpec(
        file="lleg_total.xls", sheet="1993 - 2026", orientation="matrix",
        data_row_start=4, period_header_row=3, label_col=0,
        value_col_start=1, value_col_end=7, code_prefix="p",
    )


def _recs(titulo="enero-julio 2024-2025"):
    return extract_records(_grid(titulo), _spec())


def test_ningun_par_serie_periodo_se_repite():
    claves = [(r.series, r.period) for r in _recs()]
    assert len(claves) == len(set(claves)), "los dos bloques siguen compitiendo por la clave"


def test_el_segundo_bloque_lleva_su_titulo():
    cods = {r.series for r in _recs()}
    assert any(c.endswith(".total.enero_julio_2024_2025") for c in cods), sorted(cods)


def test_el_primer_bloque_NO_se_califica():
    """Es el cuadro principal: agregarle «AÑOS» al código sería ruido, y le cambiaría el
    nombre a series que hoy están bien."""
    cods = {r.series for r in _recs()}
    assert "p.total" in cods, sorted(cods)
    assert "p.residentes" in cods, sorted(cods)


def test_los_valores_de_cada_bloque_son_los_suyos():
    d = {(r.series, r.period): r.value for r in _recs()}
    assert d[("p.total", "2024")] == 20.0                       # año completo
    assert d[("p.total.enero_julio_2024_2025", "2024")] == 11.0  # el corte


def test_sin_titulo_el_bloque_igual_se_distingue():
    """Si el emisor no titula el segundo cuadro, la serie no puede fusionarse igual: se cae a
    la coordenada de columna, que es fea pero honesta — y el guard de la frontera de escritura
    la veta antes de persistirla."""
    claves = [(r.series, r.period) for r in _recs(titulo=None)]
    assert len(claves) == len(set(claves))
