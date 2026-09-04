"""La unidad de HOJA no se le aplica a una columna que declara otra magnitud.

`sheet_unit` lee la zona de título («Índice de Precios al Consumidor», «MILLONES DE US$») y
la usa como unidad de toda columna que no traiga la suya entre paréntesis. Pero en las
planillas del BCRD la mitad de las columnas son variaciones porcentuales del cuadro, y su
magnitud la declara su PROPIO rótulo, con palabras en vez de símbolos: «Var. %»,
«Variación Porcentual», «Tasa de Inflación».

Sin este corte, 162 series del corpus quedaban con `unit='Índice'` — y `infer_nature`, que
tiene la regla correcta de que la unidad manda, las clasificaba `index`. Persistido: una
inflación mensual declarada como número índice, en el IMAE y en el IPC, que ya están
encendidos. La consecuencia no es cosmética: `nature` existe para que el consumidor sepa que
la variación de una TASA se mide en puntos porcentuales y la de un ÍNDICE en por ciento.

Leer «Variación Porcentual» como una declaración de porcentaje es LEER al emisor, no
inventar: lo escribió él, en el encabezado de la columna. Por eso el vocabulario es
explícito y corto — `tasa` a secas queda afuera, porque «tasa de cambio» no es un
porcentaje.
"""
import pytest

from shared.data.bcrd_excel.units import unidad_declarada_en_el_rotulo


@pytest.mark.parametrize("rotulo", [
    "Var. %", "Variación Porcentual", "Variación Porcentual · Mensual",
    "Inflación Subyacente · Interanual", "Tasa de Inflación", "Tasa de Crecimiento",
    "Quintil 1 · Tasa de Inflación", "Variación % Interanual",
])
def test_el_rotulo_declara_porcentaje(rotulo):
    assert unidad_declarada_en_el_rotulo(rotulo) == "%"


@pytest.mark.parametrize("rotulo", [
    "Indice", "Índice de Volumen Encadenado", "Tasa de Cambio de Referencia",
    "Reservas netas", "Acumulada", "Interanual", "Depósitos de Ahorros", "",
])
def test_lo_que_no_lo_declara_no_se_inventa(rotulo):
    assert unidad_declarada_en_el_rotulo(rotulo) is None


def test_de_punta_a_punta_la_columna_de_variacion_no_queda_como_indice():
    """El caso real: el título dice «Índice» y la columna de al lado es una variación."""
    from shared.data.bcrd_excel.inference import _series_from_columns
    from shared.data.bcrd_excel.workbook import Grid
    from shared.data.series_nature import infer_nature

    g = Grid(name="ipc", rows=[
        ["Índice de Precios al Consumidor"],
        ["Período", None, "Indice", "Variación Porcentual"],
        [None, None, None, "Mensual"],
        [2020.0, "Enero", 100.05, 0.27],
    ])
    series = _series_from_columns(g, [2, 3], 3, sheet_default="Índice")
    por_col = {s.value_col: s for s in series}
    assert por_col[2].unit == "Índice"
    assert por_col[3].unit == "%", (
        f"la variación porcentual quedó con unidad {por_col[3].unit!r}")
    assert infer_nature(unit=por_col[3].unit, code=por_col[3].code) == "rate"


@pytest.mark.parametrize("rotulo", ["Tasas de Crecimiento por Actividad Económica",
                                    "Tasas de Variación"])
def test_el_plural_tambien_lo_declara(rotulo):
    """130 series del PIB por origen decían «TasaS de Crecimiento» y el vocabulario solo
    tenía el singular."""
    assert unidad_declarada_en_el_rotulo(rotulo) == "%"


def test_la_unidad_la_puede_declarar_el_grupo_de_arriba():
    """«Acumulada» a secas no dice su magnitud; «Inflación Subyacente», una fila más arriba,
    sí. Es el caso de `ipc_subyacente_base_2019-2020.xlsx`."""
    from shared.data.bcrd_excel.inference import _series_from_columns
    from shared.data.bcrd_excel.workbook import Grid

    g = Grid(name="subyacente", rows=[
        ["Índice de Precios al Consumidor"],
        ["Período", None, "IPC", "Inflación Subyacente"],
        [None, None, "Subyacente", "Mensual", "Acumulada", "Interanual"],
        [2020.0, "Enero", 100.05, 0.27, 0.27, 5.88],
    ])
    por_col = {s.value_col: s for s in _series_from_columns(g, [2, 3, 4, 5], 3, "Índice")}
    assert por_col[2].unit == "Índice"
    for c in (3, 4, 5):
        assert por_col[c].unit == "%", f"col {c} ({por_col[c].code}) → {por_col[c].unit!r}"
