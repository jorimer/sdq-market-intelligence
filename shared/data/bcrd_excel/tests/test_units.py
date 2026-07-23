"""El detector de unidades recupera lo que el BCRD declara en la planilla.

Causa raíz que cierran: la extracción ponía ``unit=None`` en todos los registros y 216
series del BCRD quedaban en naturaleza ``unknown``, sin poder leer su momentum. El emisor
SIEMPRE declara la unidad —en un caption sobre los datos o entre paréntesis por columna—;
aquí se prueba que la leemos, y que unidad→naturaleza cae donde debe.
"""
from shared.data.bcrd_excel.units import sheet_unit, split_header_unit
from shared.data.series_nature import infer_nature


class _Grid:
    """Grid mínimo: una matriz de celdas y ``.name/.nrows/.ncols/.cell``."""
    def __init__(self, rows):
        self._rows = rows
        self.name = "hoja"

    @property
    def nrows(self):
        return len(self._rows)

    @property
    def ncols(self):
        return max((len(r) for r in self._rows), default=0)

    def cell(self, r, c):
        row = self._rows[r]
        return row[c] if c < len(row) else None


# ── caption de hoja: unidad → naturaleza ──────────────────────────────


def test_bpagos_caption_millones_us_es_flujo():
    g = _Grid([["BALANZA DE PAGOS"], [""], ["(En Millones de US$)"],
               ["CONCEPTOS", 1993, 1994]])
    u = sheet_unit(g, 3)
    assert u and "Millones de US$" in u
    assert infer_nature(unit=u, code="bpagos.balanza_comercial") == "flow"


def test_saldos_en_millones_es_stock():
    """El BCRD titula sus agregados monetarios "Saldos en millones de": son STOCKS. La
    palabra "Saldos" viaja en la unidad y debe bastar para clasificar."""
    g = _Grid([["AGREGADOS MONETARIOS"], ["Saldos en millones de: "],
               ["Año/Mes", "M3", "M2"]])
    u = sheet_unit(g, 2)
    assert u and "Saldos" in u
    assert infer_nature(unit=u, code="agregados_monetarios.m3") == "stock"


def test_promedio_ponderado_en_pct_es_tasa():
    g = _Grid([["Tasas de Interés Nominales Activas"], [""],
               ["PROMEDIO PONDERADO EN % NOMINAL ANUAL"], [""], ["Período", "0 a 90 días"]])
    u = sheet_unit(g, 4)
    assert u and "%" in u
    assert infer_nature(unit=u, code="taap_activad.plazos") == "rate"


def test_un_titulo_no_es_una_unidad():
    """"Tasas de Interés Nominales" describe la hoja pero no es la unidad: no debe ganarle
    al caption real que trae el token '%'. Sin token de unidad, no hay caption."""
    g = _Grid([["Llegada total de pasajeros no residentes"], ["1978-2026"],
               ["Período", "Total"]])
    assert sheet_unit(g, 2) is None


def test_solo_se_mira_la_zona_de_titulo():
    """Una hoja mixta lleva "Tasa de Crecimiento (%)" como rótulo de UNA columna; eso no es
    la unidad de toda la hoja. El escaneo se corta en la fila de encabezado."""
    g = _Grid([["LLEGADAS"], ["Período", "Total", "Tasa de Crecimiento (%)"],
               [1978, 100, 5.0]])
    assert sheet_unit(g, 1) is None  # no se escanea la fila 1 (encabezado)


# ── unidad por-columna entre paréntesis ───────────────────────────────


def test_split_unidad_entre_parentesis():
    name, unit = split_header_unit("PIB nominal (Millones de RD$)")
    assert name == "PIB nominal"
    assert unit == "Millones de RD$"
    assert infer_nature(unit=unit, label=name) == "flow"


def test_split_variacion_porcentual():
    name, unit = split_header_unit("Variación interanual (%)")
    assert unit == "%"
    assert infer_nature(unit=unit, label=name) == "rate"


def test_split_sin_parentesis_deja_el_nombre_intacto():
    name, unit = split_header_unit("Deflactor del PIB")
    assert name == "Deflactor del PIB"
    assert unit is None
