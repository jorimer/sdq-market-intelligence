"""Una columna con rótulo propio NO hereda el sub-encabezado de la columna vecina.

El caso que lo destapó. En el IPC por quintiles del BCRD el encabezado alterna: «Quintil 1»,
«Tasa de Inflación», «Quintil 2», «Tasa de Inflación»… y una fila más abajo las columnas de
tasa dicen «Inflación» mientras las de índice están vacías. `_header_name` caía a
``value_col - 1`` FILA POR FILA, así que la columna del índice del quintil 2 se llevaba el
«Inflación» que era del quintil 1 y salía bautizada `quintil_2_inflacion`.

Por qué importa y no es cosmético. Ese nombre afirma que el número es una TASA, y contiene
un ÍNDICE (143,4). Quien consuma la serie después no tiene cómo saber que el rótulo miente:
es la doctrina del sujeto que viaja con el número, rota en el punto donde se fabrica el
nombre. La caída al vecino sigue existiendo —hay planillas donde el rótulo sí está una
columna a la izquierda—, pero solo cuando la columna no tiene rótulo PROPIO en ninguna fila.
"""

from shared.data.bcrd_excel.inference import _header_name


class _Grid:
    """Rejilla mínima: `filas` es {(fila, col): valor}."""

    def __init__(self, filas):
        self._f = filas

    def cell(self, r, c):
        return self._f.get((r, c))


def test_una_columna_con_rotulo_propio_no_hereda_el_del_vecino():
    # fila 3: rótulos alternos · fila 4: solo las columnas de tasa traen sub-encabezado
    g = _Grid({(3, 2): "Quintil 1", (3, 3): "Tasa de Inflación", (3, 4): "Quintil 2",
               (4, 3): "Inflación", (4, 5): "Inflación"})
    assert _header_name(g, 4, 5) == "Quintil 2"       # el índice NO se llama «inflación»
    assert "Inflación" in _header_name(g, 3, 5)       # la tasa sí


def test_la_caida_al_vecino_SIGUE_valiendo_cuando_la_columna_no_tiene_rotulo():
    """Es el caso para el que se escribió: el rótulo está una columna a la izquierda."""
    g = _Grid({(3, 5): "Reservas netas"})
    assert _header_name(g, 6, 5) == "Reservas netas"


def test_sin_rotulo_en_ninguna_parte_devuelve_la_coordenada_y_no_inventa():
    g = _Grid({})
    assert _header_name(g, 7, 5) == "col7"
