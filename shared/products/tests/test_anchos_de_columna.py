"""Los anchos de una tabla markdown se reparten por CONTENIDO, no en partes iguales.

El reparto igualitario salió en el PDF que se vende: la tabla de siete columnas del panel de
transacciones partía «Intercommercia / l Bank Limited» a media palabra en la columna de la
adquirida mientras «Año» y «P/B» gastaban la misma franja en blanco. Lo encontró leer el PDF,
no un test — por eso ahora hay uno.
"""
from reportlab.lib.units import inch

from shared.products.render import anchos_de_columna

TOTAL = 6.5 * inch


def test_la_columna_larga_recibe_mas_que_la_corta():
    header = ["Año", "Comprador", "Adquirida", "País", "P/B", "Base", "Corte del libro"]
    rows = [["2013", "JMMB Group", "Intercommercial Bank Limited (100 % del capital)",
             "Trinidad y Tobago", "0.83×", "contable", "2013-10"]]
    anchos = anchos_de_columna(header, rows, TOTAL)
    igual = TOTAL / len(header)
    assert anchos[2] > igual * 1.6, "la adquirida no recibe el ancho que su contenido pide"
    assert anchos[0] < igual, "el año sigue gastando la misma franja que un nombre"
    assert anchos[2] == max(anchos) and anchos[0] == min(anchos)


def test_la_suma_es_el_total_y_nada_se_va_de_los_topes():
    header = ["a", "b" * 80, "c"]
    rows = [["x", "y" * 200, "z"]]
    anchos = anchos_de_columna(header, rows, TOTAL)
    assert abs(sum(anchos) - TOTAL) < 1e-6
    igual = TOTAL / 3
    # Los topes valen ANTES de normalizar: el techo de 2,5 y el piso de 0,5 acotan el reparto
    # crudo, y la normalización solo lo reescala al total.
    assert max(anchos) / min(anchos) <= 5.0 + 1e-6


def test_una_tabla_pareja_queda_como_estaba():
    """El contrapeso: la inmensa mayoría de las tablas tienen columnas parecidas, y su
    aspecto no puede cambiar."""
    header = ["Cierre", "ROE"]
    rows = [["2024-12-31", "12.10 %"], ["2025-12-31", "13.20 %"]]
    anchos = anchos_de_columna(header, rows, TOTAL)
    assert abs(anchos[0] - anchos[1]) < TOTAL * 0.10


def test_sin_filas_reparte_por_el_encabezado():
    anchos = anchos_de_columna(["a", "b"], [], TOTAL)
    assert abs(sum(anchos) - TOTAL) < 1e-6 and len(anchos) == 2
