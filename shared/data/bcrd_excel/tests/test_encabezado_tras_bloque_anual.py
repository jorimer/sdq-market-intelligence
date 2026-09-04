"""Un guion no es un rótulo, y el encabezado puede estar más arriba de seis filas.

`ipc_subyacente_base_2019-2020.xlsx` publica primero un bloque de cierres anuales
(«Dic. 2000»… «Dic. 2025») y recién después la serie mensual. El buscador de nombres mira
las seis filas inmediatamente encima del primer dato: ahí no está el encabezado —está el
final del bloque anual, cuyas celdas de inflación mensual e interanual dicen `-` porque un
cierre de diciembre no las tiene.

Resultado: la columna del índice salía `col2` (nombre por coordenada) y las tres de inflación
tomaban el guion como nombre, quedando `x`, `x_c4`, `x_c5`. Dos de ellas ni siquiera se
persistían —el veto de códigos por coordenada las frenaba en la frontera de escritura— y las
otras dos entraban sin decir qué miden.

Dos reglas, las dos estrechas a propósito:

1. Un marcador de dato ausente (`-`, `...`, `n.d.`) NO es un rótulo. Es el mismo vocabulario
   que `coerce_num` ya trata como vacío: si no es un número, tampoco es un nombre.
2. Cuando la ventana fija no da NINGÚN rótulo para una columna, se sigue buscando hacia
   arriba. Solo entonces: donde hoy hay un nombre, no se toca — un renombrado masivo
   huerfanaría las series ya persistidas.
"""
from shared.data.bcrd_excel.inference import _header_name
from shared.data.bcrd_excel.workbook import Grid


def _grid():
    filas = [
        ["Índice de Precios al Consumidor"],
        ["Base Anual: Octubre 2019 - Septiembre 2020"],
        ["Período", None, "IPC", "Inflación Subyacente"],
        [None, None, "Subyacente", "Mensual", "Acumulada", "Interanual"],
    ]
    # El bloque de cierres anuales: doce filas entre el encabezado y la serie mensual.
    for anio in range(2000, 2012):
        filas.append([f"Dic. {anio}", None, 27.4 + anio - 2000, "-", 6.5, "-"])
    filas.append([None] * 6)
    filas.append([None] * 6)
    filas.append([2000.0, "Enero", 25.84, 0.31, 0.31, 5.88])
    return Grid(name="ipc subyacente", rows=filas)


DATA_ROW0 = 18


def test_el_indice_no_se_llama_por_su_coordenada():
    nombre = _header_name(_grid(), 2, DATA_ROW0)
    assert "col2" not in nombre, f"la columna del índice se llamó «{nombre}»"
    assert "subyacente" in nombre.lower()


def test_el_guion_del_cierre_anual_no_bautiza_la_serie():
    for col, esperado in ((3, "mensual"), (5, "interanual")):
        nombre = _header_name(_grid(), col, DATA_ROW0)
        assert nombre.strip() not in {"-", ""}, (
            f"la columna {col} tomó el marcador de dato ausente como nombre")
        assert esperado in nombre.lower(), f"la columna {col} se llamó «{nombre}»"


def test_los_cuatro_nombres_son_distintos():
    nombres = [_header_name(_grid(), c, DATA_ROW0) for c in (2, 3, 4, 5)]
    assert len(set(nombres)) == 4, f"nombres repetidos: {nombres}"


def _grid_eje_doble():
    """`Año | Semestre | valor`: el título del cuadro está DOS columnas a la izquierda.

    Es la hoja «Semestral 2000-2016» de `tasa_ocupacion.xls`. La única columna de valor no
    tiene rótulo propio ni en su columna ni en la de al lado —las dos son ejes, año y
    semestre— y salía llamándose `col2`.
    """
    filas = [
        ["BANCO CENTRAL DE LA REPÚBLICA DOMINICANA"],
        ["DEPARTAMENTO DE CUENTAS NACIONALES"],
        ["DIVISION DE ENCUESTAS"],
        [None],
        ["Tasa de Ocupación Semestral"],
        [None],
        [2016.0, "Abril", 50.41],
        [None, "Octubre", 50.55],
    ]
    return Grid(name="Semestral 2000-2016", rows=filas)


def test_la_unica_columna_de_valor_toma_el_titulo_del_cuadro():
    nombre = _header_name(_grid_eje_doble(), 2, 6, cols_de_valor={2})
    assert "col2" not in nombre, f"la columna de valor se llamó «{nombre}»"
    assert "ocupaci" in nombre.lower(), f"se llamó «{nombre}»"


def test_el_rodeo_no_cruza_otra_columna_de_valor():
    """El rodeo hacia la izquierda SALTEA las columnas que ya son series.

    La caída de una sola columna (`value_col - 1`) es anterior y deliberada —hay planillas
    donde el rótulo está justo al lado, ver `test_el_rotulo_no_se_le_roba_al_vecino`—. Lo
    que se estrena acá es el rodeo MÁS LEJOS, y ese no puede llevarse el nombre de otra
    serie: prefiere quedarse sin nombre.
    """
    # col 3 es la serie sin rótulo · col 2 está vacía · col 1 es OTRA serie, con rótulo
    filas = [[None, "Reservas netas", None, None],
             ["1990", 10.0, None, 20.0]]
    nombre = _header_name(Grid(name="h", rows=filas), 3, 1, cols_de_valor={1, 3})
    assert nombre == "col3", f"el rodeo se llevó el rótulo de otra serie: «{nombre}»"
