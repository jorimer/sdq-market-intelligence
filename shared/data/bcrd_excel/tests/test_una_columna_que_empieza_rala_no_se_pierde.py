"""Una columna con datos no se descarta por cómo EMPIEZA, ni por cómo TERMINA.

`_value_columns` decidía si una columna trae datos mirando **solo las primeras 80 filas**.
Una serie que arranca rala y se llena después quedaba descartada entera, sin aviso: no es que
saliera con huecos, es que no existía.

Y medir solo sobre el archivo completo tiene el defecto simétrico — una serie DESCONTINUADA,
densa al principio y vacía después, cae por debajo del umbral.

**Medido sobre los 33 archivos habilitados**, cada ventana por separado cuesta una columna
real, y las dos están en `Serie_TPM.xlsx`:

* solo el arranque pierde **«Préstamo»** —la facilidad de expansión del BCRD, 164 valores, el
  techo del corredor de política—, que arranca rala y se llena;
* solo el archivo entero pierde **«Lombarda»** —109 valores—, densa al principio y
  descontinuada después.

Con la unión el archivo pasa de 3 series a 4 y queda el corredor completo. Fuera de esas dos,
ninguna columna del corpus cambia de estado.
"""
from typing import List

from shared.data.bcrd_excel.inference import _value_columns
from shared.data.bcrd_excel.workbook import Grid

_MESES = ("Ene", "Feb", "Mar", "Abr", "May", "Jun",
          "Jul", "Ago", "Sep", "Oct", "Nov", "Dic")
#: 200 filas de datos: más que la ventana de 80, que es lo que hace visible la diferencia.
_N = 200


def _grid(patron_a, patron_b) -> Grid:
    """Dos columnas de valores; cada patrón decide si la fila `i` trae número o vacío."""
    filas: List[list] = [["Cuadro"], [], ["Año", "Mes", "A", "B"]]
    for i in range(_N):
        filas.append([2000 + i // 12, _MESES[i % 12],
                      1.0 if patron_a(i) else None,
                      2.0 if patron_b(i) else None])
    return Grid(name="H", rows=filas)


def _cols(g: Grid) -> List[int]:
    return _value_columns(g, month_col=1, data_row0=3)


def test_una_columna_que_EMPIEZA_rala_y_se_llena_entra():
    """El caso «Préstamo»: nada en las primeras 80 filas, densa en el resto."""
    g = _grid(lambda i: i >= 100, lambda i: True)
    assert 2 in _cols(g), (
        "la columna que arranca vacía y se llena después quedó descartada entera: mirar "
        "solo el arranque la borra sin aviso")


def test_una_columna_DESCONTINUADA_sigue_entrando():
    """El caso «Lombarda», y el contraejemplo que impide arreglar lo de arriba mirando solo
    el archivo completo: densa al principio, vacía después."""
    g = _grid(lambda i: i < 70, lambda i: True)
    assert 2 in _cols(g), (
        "la columna densa al principio y descontinuada después quedó fuera: medir solo sobre "
        "el archivo entero la hunde bajo el umbral")


def test_una_columna_RALA_EN_TODAS_PARTES_sigue_fuera():
    """La unión no ensancha el criterio. Sin esto, «entra si es densa en cualquier ventana»
    podría degenerar en «entra siempre», y el filtro dejaría de filtrar."""
    g = _grid(lambda i: i % 10 == 0, lambda i: True)   # 10 % de densidad en las dos ventanas
    assert 2 not in _cols(g), "una columna rala en todas partes entró igual"


def test_una_columna_VACIA_sigue_fuera():
    g = _grid(lambda i: False, lambda i: True)
    assert _cols(g) == [3], _cols(g)
