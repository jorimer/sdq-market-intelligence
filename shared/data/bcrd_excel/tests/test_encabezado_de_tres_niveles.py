"""Con tres niveles de encabezado, el grupo está ARRIBA, no a la izquierda.

El IMAE publica tres cuadros lado a lado —Serie Original, Serie Desestacionalizada, Serie
Tendencia-Ciclo— y bajo cada uno «Índice» y «Variación porcentual (%)», y bajo esta última
«Interanual | Acumulada | Promedio 12 meses». Nueve columnas comparten tres rótulos.

`_grupo_a_la_izquierda` desempataba con el rótulo de la COLUMNA VECINA, que en un encabezado
de dos niveles es el grupo (en el IPC por quintiles el índice del quintil está justo a la
izquierda de su tasa) pero acá no lo es. Resultado en el archivo real, que está ENCENDIDO:

* `acumulada_promedio_12_meses` — la columna es «Promedio 12 meses» de la Serie Original, y
  el nombre le atribuye la «Acumulada» de al lado.
* `interanual`, `acumulada`, `promedio_12_meses` a secas: tres columnas de la Serie
  Desestacionalizada sin decir de qué serie son.
* `interanual_c13` y `promedio_12_meses_c15`: desempate por COORDENADA, que el veto de la
  frontera de escritura descarta — dos series de la Tendencia-Ciclo que no se persistían y
  nadie echaba de menos.

La regla: cuando un rótulo se repite, el calificador se busca primero en las filas de
ARRIBA, rellenando desde la izquierda (que es como Excel escribe una celda combinada), y
recién si no hay nada arriba se cae al vecino de la izquierda — el caso de los quintiles,
que sigue valiendo.
"""
from shared.data.bcrd_excel.inference import _series_from_columns
from shared.data.bcrd_excel.workbook import Grid

_BLOQUES = {2: "Serie Original", 6: "Serie Desestacionalizada", 11: "Serie Tendencia-Ciclo"}
_METRICAS = {3: "Interanual", 4: "Acumulada", 5: "Promedio 12 meses",
             8: "Interanual", 9: "Acumulada", 10: "Promedio 12 meses",
             13: "Interanual", 14: "Acumulada", 15: "Promedio 12 meses"}


def _grid():
    ancho = 16
    f5 = [None] * ancho
    f6 = [None] * ancho
    f7 = [None] * ancho
    f5[0] = "Período"
    for c, rotulo in _BLOQUES.items():
        f5[c] = rotulo
        f6[c] = "Índice"
    for c in (3, 7, 12):
        f6[c] = "Variación porcentual (%)"
    f7[7] = f7[12] = "Respecto al período anterior"
    for c, rotulo in _METRICAS.items():
        f7[c] = rotulo
    datos = [None] * ancho
    datos[1] = "Enero"
    for c in range(2, ancho):
        datos[c] = 50.0 + c
    return Grid(name="IMAE", rows=[[None]] * 5 + [f5, f6, f7, datos, list(datos)])


_COLS = [2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15]


def _series():
    return _series_from_columns(_grid(), _COLS, 8, sheet_default="Índice")


def test_ninguna_columna_se_desempata_por_coordenada():
    malos = [s.code for s in _series() if "_c1" in s.code or s.code.endswith("_c5")]
    assert not malos, f"desempate por coordenada: {malos}"


def test_cada_columna_dice_de_que_cuadro_es():
    por_col = {s.value_col: s for s in _series()}
    for col, bloque in ((5, "original"), (10, "desestacionalizada"), (15, "tendencia")):
        assert bloque in por_col[col].code, (
            f"la columna {col} se llamó «{por_col[col].code}» y no dice de qué cuadro es")


def test_nadie_se_lleva_el_rotulo_del_vecino():
    por_col = {s.value_col: s for s in _series()}
    assert "acumulada" not in por_col[5].code, (
        f"«Promedio 12 meses» se llevó la «Acumulada» de al lado: {por_col[5].code}")


def test_los_catorce_codigos_son_distintos():
    codigos = [s.code for s in _series()]
    assert len(set(codigos)) == len(codigos), f"códigos repetidos en {codigos}"


def test_la_variacion_porcentual_no_queda_con_unidad_de_indice():
    por_col = {s.value_col: s for s in _series()}
    for col in (3, 4, 5, 8, 9, 10, 13, 14, 15):
        assert por_col[col].unit == "%", (
            f"la columna {col} ({por_col[col].code}) quedó con unidad "
            f"{por_col[col].unit!r}")
    assert por_col[2].unit == "Índice"
