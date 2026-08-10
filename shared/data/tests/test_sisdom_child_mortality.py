"""Mortalidad infantil provincial (SISDOM `04 3 035b`) — lógica pura, sin red.

Es una serie PUBLICADA y no una variable del índice, así que el test que más importa no
es el de extracción sino el de que el emisor marca lo no disponible con «. . .» y eso no
se cuela como cero.
"""
import io

import openpyxl
import pytest

from shared.data.sisdom_child_mortality import (
    SHEET,
    THEME,
    parse_child_mortality,
)
from shared.data.sisdom_common import SisdomUnavailable

SIN_DATO = ". . ."


def _libro(bloques, hoja=SHEET):
    wb = openpyxl.Workbook()
    wb.active.title = "otra"
    wb.active.append(["ruido"])
    ws = wb.create_sheet(hoja)
    ws.append(["SISTEMA DE INDICADORES SOCIALES"])
    ws.append(["Área Temática: Salud"])
    ws.append(["Desagregaciones", "1996", "2002", "2007"])
    for rotulo, vals in bloques:
        ws.append([rotulo, *vals])
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def test_extrae_el_bloque_provincial_y_descarta_lo_no_disponible():
    """El emisor escribe '. . .' donde no hay dato. Tomarlo por cero convertiría una
    provincia sin medición en la de menor mortalidad del país."""
    filas = parse_child_mortality(_libro([
        ("Zona Residencia", [65.8, 40.0, 38.0]),      # antes del bloque: se ignora
        ("Provincia", ["", "", ""]),
        ("Azua", [SIN_DATO, 39, 35]),
        ("Barahona", [SIN_DATO, 37, 40]),
        ("Espaillat", [SIN_DATO, SIN_DATO, 11]),
    ]))
    assert ("azua", 2002, 39.0) in filas and ("azua", 2007, 35.0) in filas
    assert ("espaillat", 2007, 11.0) in filas
    assert not [f for f in filas if f[1] == 1996]     # esa columna no tiene dato
    assert all(v > 0 for _s, _y, v in filas)


def test_el_bloque_termina_donde_dejan_de_ser_provincias():
    """Después del bloque vienen notas y fuentes; seguir leyendo metería basura."""
    filas = parse_child_mortality(_libro([
        ("Provincia", ["", "", ""]),
        ("Azua", [SIN_DATO, 39, 35]),
        ("Notas:", ["", "", ""]),
        ("a) En el 2002 el número de Regiones…", [SIN_DATO, 99, 99]),
    ]))
    assert filas == [("azua", 2002, 39.0), ("azua", 2007, 35.0)]


@pytest.mark.parametrize("valor", [0, -3, 250, "n/d", None])
def test_valores_imposibles_para_una_tasa_por_mil_se_descartan(valor):
    filas = parse_child_mortality(_libro([
        ("Provincia", ["", "", ""]),
        ("Azua", [SIN_DATO, valor, 35]),
    ]))
    assert filas == [("azua", 2007, 35.0)]


def test_sin_bloque_provincial_levanta_con_el_motivo():
    with pytest.raises(SisdomUnavailable, match="no declara el bloque"):
        parse_child_mortality(_libro([("Zona Residencia", [1, 2, 3])]))


def test_el_tema_NO_es_child_mortality():
    """Comparte concepto con la serie de WDI pero no metodología —una es estimación
    modelada anual y esta una encuesta de hogares—. El mismo código invitaría a
    graficarlas juntas, y además la haría entrar al IDM por la puerta de atrás."""
    assert THEME == "endesa_child_mortality"
    assert THEME != "child_mortality"
