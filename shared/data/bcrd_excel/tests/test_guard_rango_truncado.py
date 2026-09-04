"""Un spec que corta el rango antes del último período del encabezado MARCA el archivo.

**Por qué existe.** Dos veces en el mismo día un spec dejó columnas con dato sin leer y la
serie salió corta sin que nada lo dijera: `PIB$_Trim_Acum` terminaba cinco años antes que sus
hojas hermanas, y `bpagos`/`lleg_total` perdían sus últimos años porque el rótulo venía
marcado como preliminar. En los tres casos el dato ESTABA, el encabezado lo declaraba, y la
única señal era comparar una serie contra otra a mano.

Las causas se arreglaron —la vista previa del modelo declara su recorte, y el eje temporal
reconoce `2011*` y `2021 (p)`— pero **la lección escrita no alcanza**: la próxima planilla con
un rótulo raro vuelve a truncar en silencio. El guard compara lo que el spec LEE contra los
períodos que el encabezado DECLARA, y marca la diferencia.

**La regla no es «hay números más allá del rango».** Un cuadro con dos bloques —niveles y
luego «Tasas de Crecimiento», con encabezados `92/91`— tiene números fuera del rango y está
bien que no los lea: `pib_gasto.xls` daba ese falso positivo. Lo que se exige es que no quede
afuera una columna cuyo ENCABEZADO declara un período y que además trae dato.
"""
from shared.data.bcrd_excel.inference import periodos_sin_leer
from shared.data.bcrd_excel.spec import ExtractionSpec
from shared.data.bcrd_excel.workbook import Grid


def _grid(encabezado, fila_datos):
    return Grid(name="H", rows=[encabezado, fila_datos])


def _spec(c1):
    return ExtractionSpec(file="f", sheet="H", orientation="matrix", data_row_start=1,
                          period_header_row=0, label_col=0, value_col_start=1,
                          value_col_end=c1)


def test_marca_cuando_el_rango_deja_afuera_un_ano_con_dato():
    g = _grid(["Concepto", 2010, 2011, 2012], ["Agro", 1.0, 2.0, 3.0])
    assert periodos_sin_leer(g, _spec(3)) == [(3, 2012)]


def test_no_marca_cuando_lee_todo():
    g = _grid(["Concepto", 2010, 2011, 2012], ["Agro", 1.0, 2.0, 3.0])
    assert periodos_sin_leer(g, _spec(4)) == []


def test_no_marca_el_SEGUNDO_BLOQUE_de_un_cuadro():
    """El falso positivo de `pib_gasto.xls`: de la columna 3 en adelante hay otro bloque
    —tasas de crecimiento, `92/91`— con números y sin período en el encabezado."""
    g = _grid(["Concepto", 2010, 2011, "Tasas de Crecimiento", "11/10"],
              ["Agro", 1.0, 2.0, None, 5.5])
    assert periodos_sin_leer(g, _spec(3)) == []


def test_no_marca_una_columna_de_periodo_VACIA():
    """Si el encabezado declara un año pero la columna no trae dato, no hay nada que perder:
    marcarlo sería ruido y el guard dejaría de mirarse."""
    g = _grid(["Concepto", 2010, 2011, 2012], ["Agro", 1.0, 2.0, None])
    assert periodos_sin_leer(g, _spec(3)) == []


def test_un_rango_ABIERTO_nunca_trunca():
    g = _grid(["Concepto", 2010, 2011, 2012], ["Agro", 1.0, 2.0, 3.0])
    assert periodos_sin_leer(g, _spec(None)) == []


def test_sin_fila_de_periodos_no_hay_nada_que_comparar():
    g = _grid(["Concepto", 2010, 2011], ["Agro", 1.0, 2.0])
    sp = _spec(2)
    sp.period_header_row = None
    assert periodos_sin_leer(g, sp) == []


def test_reconoce_el_ano_PRELIMINAR_al_marcarlo():
    """La firma exacta de los dos casos reales: la columna perdida venía rotulada `2011*`."""
    g = _grid(["Concepto", 2010, "2011*", "2012**"], ["Agro", 1.0, 2.0, 3.0])
    assert periodos_sin_leer(g, _spec(2)) == [(2, 2011), (3, 2012)]
