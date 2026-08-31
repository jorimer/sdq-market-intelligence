"""Dos columnas que se llaman igual se desempatan por su GRUPO, no por la coordenada.

**El defecto.** En el IPC por quintiles del BCRD el encabezado alterna «Quintil 1», «Tasa de
Inflación», «Quintil 2», «Tasa de Inflación»…: las cinco columnas de tasa se llaman IGUAL, y
lo que las distingue —el quintil— está en la columna del índice, a la izquierda. El
desempate era el ÍNDICE DE COLUMNA, así que salían `tasa_de_inflacion_c5`, `_c7`, `_c9`,
`_c11`: códigos que no dicen de qué quintil es la tasa. Se persistieron DIECIOCHO series así
—quintiles, IPC por región e IMAE—, tasas sin su población al lado de índices que sí la
nombran, y quien las consuma después no tiene cómo saber que el rótulo no identifica nada.

**Por qué nombrarlas y no descartarlas.** La primera reacción fue vetarlas en la escritura:
una serie que no nombra su sujeto no se sirve. Estaba mal. Se verificó contra el dato que
cada una de las cinco tasas coincide EXACTAMENTE —error 0,00000 pp sobre setenta puntos— con
la variación mensual del índice del quintil que este mapeo le asigna. No eran series
inservibles: eran series mal nombradas, y entre descartar y nombrar hay cinco series reales.
Es la misma lección que costó seis horas con `tasaPorDeuda`: ir a la definición del emisor
antes de decidir qué hacer con un campo que no se entiende.
"""

from shared.data.bcrd_excel.inference import _grupo_a_la_izquierda, _series_from_columns


class _Grid:
    """Rejilla mínima: `filas` es {(fila, col): valor}."""

    def __init__(self, filas, ncols=20, nrows=40):
        self._f = filas
        self.ncols = ncols
        self.nrows = nrows

    def cell(self, r, c):
        return self._f.get((r, c))


def _quintiles():
    """El encabezado real del IPC por quintiles: índice y tasa alternados, con el rótulo del
    quintil solo sobre la columna del índice."""
    filas = {}
    for i, col in enumerate(range(2, 12, 2), start=1):
        filas[(3, col)] = f"Quintil {i}"
        filas[(3, col + 1)] = "Tasa de Inflación"
        filas[(4, col + 1)] = "Inflación"
    return _Grid(filas)


def test_las_cinco_tasas_salen_con_SU_quintil_y_no_con_la_coordenada():
    specs = _series_from_columns(_quintiles(), list(range(2, 12)), 5, None)
    codigos = [s.code for s in specs]
    assert not [c for c in codigos if c.endswith(("_c5", "_c7", "_c9", "_c11"))], (
        f"quedó un código desempatado por coordenada: {codigos}")
    for i in range(1, 6):
        assert any(f"quintil_{i}" in c and "inflacion" in c for c in codigos), (
            f"la tasa del quintil {i} no lleva su quintil en el código: {codigos}")


def test_los_INDICES_conservan_su_nombre_propio():
    """El desempate solo actúa sobre la colisión; no debe tocar a quien ya se llamaba bien."""
    specs = {s.value_col: s.code for s in _series_from_columns(
        _quintiles(), list(range(2, 12)), 5, None)}
    for i, col in enumerate(range(2, 12, 2), start=1):
        assert specs[col] == f"quintil_{i}"


def test_cada_serie_queda_con_un_codigo_UNICO():
    specs = _series_from_columns(_quintiles(), list(range(2, 12)), 5, None)
    codigos = [s.code for s in specs]
    assert len(codigos) == len(set(codigos)), f"códigos repetidos: {codigos}"


def test_sin_grupo_a_la_izquierda_cae_a_la_COORDENADA_y_no_inventa():
    """Si el vecino no aporta un rótulo distinto, no hay con qué desambiguar: la coordenada
    es fea pero honesta, y es preferible a inventar una población."""
    g = _Grid({(3, 2): "Total", (3, 3): "Total"})
    specs = _series_from_columns(g, [2, 3], 5, None)
    assert specs[1].code.endswith("_c3")


def test_no_arrastra_el_rotulo_de_un_bloque_AJENO():
    """La búsqueda mira dos columnas a la izquierda. Más lejos empezaría a tomar prestado el
    encabezado de otro grupo, que es un nombre tan falso como la coordenada."""
    g = _Grid({(3, 1): "Bloque lejano", (3, 5): "Total", (3, 9): "Total"})
    assert _grupo_a_la_izquierda(g, 9, 5, "Total") is None


def test_un_rotulo_que_REPITE_el_propio_no_desambigua():
    g = _Grid({(3, 4): "Inflación", (3, 5): "Inflación"})
    assert _grupo_a_la_izquierda(g, 5, 5, "Inflación") is None
