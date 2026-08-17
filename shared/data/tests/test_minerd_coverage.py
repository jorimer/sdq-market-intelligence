"""Cobertura educativa del MINERD (tablero Power BI) — lógica pura, sin red.

Las filas de ejemplo tienen la forma REAL que devuelve el DSR, incluidos sus dos
rasgos incómodos: el mismo campo llega unas veces como número y otras como texto, y
entre las provincias vienen mezcladas filas de agregado (``TOTAL REGION``, ``TOTAL
PAIS``) que significan cosas distintas y no se pueden tratar igual.
"""
import pytest

from shared.data.minerd_coverage import (
    MinerdCoverageError,
    build_query,
    parse_coverage_rows,
    school_year_to_calendar,
)


def _fila(anio, nivel, provincia, region, cobertura):
    return [anio, nivel, provincia, region, cobertura]


BASE = [
    _fila("2024-2025", "Secundario", "AZUA", "VALDESIA", "74.5"),
    _fila("2024-2025", "Secundario", "PEDERNALES", "ENRIQUILLO", 55.5),   # número, no texto
    _fila("2024-2025", "Secundario", "TOTAL REGION", "VALDESIA", "74.4"),
    _fila("2024-2025", "Secundario", "TOTAL PAIS", "TOTAL PAIS", "71.0"),
    _fila("2024-2025", "Primario", "AZUA", "VALDESIA", "95.0"),           # otro nivel
]


def test_extrae_provincia_y_region_del_mismo_tablero():
    """La fila de agregado regional trae el valor de la región. Promediar las
    provincias para reconstruirlo habría sido inventar un dato: sin ponderar por
    población escolar, ese promedio no es la cobertura de la región."""
    filas = parse_coverage_rows(BASE)
    assert ("provincia", "azua", 2025, 74.5) in filas
    assert ("provincia", "pedernales", 2025, 55.5) in filas
    assert ("region", "valdesia", 2025, 74.4) in filas
    assert ("pais", "pais", 2025, 71.0) in filas
    assert len(filas) == 4          # el nivel primario queda fuera; el país YA no


def test_el_total_de_pais_se_captura_y_no_se_confunde_con_el_regional():
    """Los dos empiezan con 'TOTAL' y significan cosas distintas.

    El de país se descartaba, y ese descarte tuvo consecuencias: sin la cifra nacional,
    quien comparaba contra una meta de país terminaba usando la de una región. Ahora se
    captura con su propio nivel geográfico — y el orden importa, porque
    `_is_region_total` aceptaría su etiqueta para después no resolver ninguna región y
    perderla en silencio."""
    solo_pais = [_fila("2024-2025", "Secundario", "TOTAL PAIS", "TOTAL PAIS", "71.0")]
    assert parse_coverage_rows(solo_pais) == [("pais", "pais", 2025, 71.0)]


def test_el_nivel_BASICO_sale_del_mismo_tablero():
    """Indicador 2.9 de la END. El tablero lo rotula «Primario» y la ley «básica»."""
    from shared.data.minerd_coverage import PRIMARY_LEVELS
    filas = parse_coverage_rows(BASE, PRIMARY_LEVELS)
    assert ("provincia", "azua", 2025, 95.0) in filas
    assert not any(f[3] == 74.5 for f in filas), "se coló una fila de secundaria"


@pytest.mark.parametrize("etiqueta,esperado", [
    ("2023-2024", 2024),
    (" 2018-2019 ", 2019),
    ("2024-2025", 2025),
])
def test_el_ano_lectivo_se_estampa_al_segundo_tramo(etiqueta, esperado):
    """Misma convención que el parser anterior: si cambiara, la serie se cortaría o se
    duplicaría justo al cambiar de fuente."""
    assert school_year_to_calendar(etiqueta) == esperado


@pytest.mark.parametrize("etiqueta", ["2024", "2024-2026", "2024/2025", "", None, "s/f"])
def test_ano_lectivo_invalido_no_se_adivina(etiqueta):
    assert school_year_to_calendar(etiqueta) is None


@pytest.mark.parametrize("valor", ["", None, "n/d", -1, 101, "abc"])
def test_cobertura_fuera_de_rango_o_ilegible_se_descarta(valor):
    filas = [_fila("2024-2025", "Secundario", "AZUA", "VALDESIA", valor),
             _fila("2024-2025", "Secundario", "BARAHONA", "ENRIQUILLO", "60.0")]
    assert parse_coverage_rows(filas) == [("provincia", "barahona", 2025, 60.0)]


def test_medio_cuenta_como_secundaria():
    """'Medio' es la etiqueta previa a 2014; se acepta por continuidad de la serie."""
    filas = parse_coverage_rows([_fila("2013-2014", "Medio", "AZUA", "VALDESIA", "50.0")])
    assert filas == [("provincia", "azua", 2014, 50.0)]


def test_sin_filas_utilizables_levanta_en_vez_de_devolver_vacio():
    """Un vacío silencioso aguas arriba se lee como 'la fuente no publicó'. Ya pasó
    con el SIUBEN el 2026-08-09; acá se corta de raíz."""
    with pytest.raises(MinerdCoverageError, match="ninguna fila utilizable"):
        parse_coverage_rows([_fila("2024-2025", "Primario", "AZUA", "VALDESIA", "95.0")])


def test_la_consulta_pide_las_cinco_columnas_y_acota_el_volumen():
    q = build_query(7552821)
    cmd = q["queries"][0]["Query"]["Commands"][0]["SemanticQueryDataShapeCommand"]
    props = [s["Column"]["Property"] for s in cmd["Query"]["Select"]]
    assert props == ["Año", "Nivel", "Provincia", "Región", "Cobertura"]
    assert cmd["Query"]["From"][0]["Entity"] == "Data 2"
    assert cmd["Binding"]["DataReduction"]["Primary"]["Window"]["Count"] >= 1500
    assert q["modelId"] == 7552821
