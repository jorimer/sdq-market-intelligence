"""Un número de línea entre paréntesis identifica la COLUMNA, no lo que mide.

La base monetaria y los agregados monetarios cierran su encabezado con una fila de
referencias —`(1)`, `(2)`, `(4)=(1 al 3)`, `(14)= (4 al 13)`— que el BCRD usa para escribir
sus propias sumas. Es la fila más baja del encabezado, así que era la que el buscador de
nombres tomaba como rótulo propio de cada columna: salían series llamadas `me_9`, `me_11`,
`valores_3`, `valores_7`, `total_10_6_al_9`.

Dos daños. El nombre no dice qué mide —«ME» de qué, si el cuadro tiene tres bloques de
moneda extranjera—, y además el número TAPA el grupo: al contar como rótulo propio, la
cadena de encabezados de arriba (Amplia › Otros pasivos frente a otras sociedades de
depósito › Otros depósitos › ME) no llegaba a viajar con el número.

Es el mismo criterio que con el guion del dato ausente: si no nombra, no es un nombre.
"""
import pytest

from shared.data.bcrd_excel.inference import _header_name, _es_referencia_de_linea
from shared.data.bcrd_excel.workbook import Grid


@pytest.mark.parametrize("celda", ["(1)", "(14)", " (9) ", "(4)=(1 al 3)", "(14)= (4 al 13)"])
def test_reconoce_la_referencia_de_linea(celda):
    assert _es_referencia_de_linea(celda)


@pytest.mark.parametrize("celda", ["(ME)", "(p)", "Valores", "(MN)", "Base monetaria amplia",
                                   "Trimestre (1)ero"])
def test_no_confunde_un_rotulo_entre_parentesis(celda):
    assert not _es_referencia_de_linea(celda)


def _grid():
    ancho = 12
    f7 = [None] * ancho
    f8 = [None] * ancho
    f9 = [None] * ancho
    f10 = [None] * ancho
    f7[2] = "Restringida"
    f7[5] = "Amplia"
    f8[9] = "Otros pasivos frente a otras sociedades de depósito"
    f9[9] = "Otros depósitos"
    f10[9] = " (MN)"
    f10[10] = " (ME)"
    f8[11] = "Depósitos y valores otros sectores"
    f10[11] = " (ME)"
    linea = [None] * ancho
    for i, c in enumerate(range(2, ancho)):
        linea[c] = f"({i + 1})"
    datos = [2001.0, "Dic"] + [100.0 + c for c in range(2, ancho)]
    return Grid(name="III.1.Base Monetaria", rows=[f7, f8, f9, f10, linea, datos])


def test_el_numero_de_linea_no_bautiza_la_columna():
    nombre = _header_name(_grid(), 10, 5, cols_de_valor=set(range(2, 12)))
    assert "(9)" not in nombre, f"quedó el número de línea: «{nombre}»"
    assert "ME" in nombre


def test_las_dos_columnas_de_moneda_extranjera_dicen_de_que_bloque_son():
    """El cuadro real tiene «(ME)» dos veces, bajo bloques distintos. Con el número de línea
    contando como rótulo salían `me_9` y `me_11`; sin él, las dos colisionan y el desempate
    les da su cadena de grupos."""
    from shared.data.bcrd_excel.inference import _series_from_columns

    series = {s.value_col: s.code for s in
              _series_from_columns(_grid(), list(range(2, 12)), 5, None)}
    for col in (10, 12 - 1):
        assert not series[col].startswith("me_"), (
            f"la columna {col} se llamó «{series[col]}»")
    assert series[10] != series[11]
    assert "otros" in series[10]
