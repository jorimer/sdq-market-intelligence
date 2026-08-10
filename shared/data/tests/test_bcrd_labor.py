"""ENCFT del BCRD — parser de informalidad (lógica pura, sin red).

La planilla se arma acá con la forma REAL del libro del BCRD: ventanas móviles de
cuatro trimestres en el encabezado, de las cuales solo algunas son de año calendario, y
dos filas de informalidad que miden cosas distintas y se parecen peligrosamente.
"""
import io

import openpyxl
import pytest

from shared.data.bcrd_labor import (
    BcrdLaborUnavailable,
    INFORMALITY_LABEL,
    SHEET,
    parse_informality,
)


def _libro(filas, hoja=SHEET):
    wb = openpyxl.Workbook()
    wb.active.title = "Indicadores"          # otra hoja: NO debe ganar
    wb.active.append(["Ocupación Informal", 99.9])
    ws = wb.create_sheet(hoja)
    for f in filas:
        ws.append(f)
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


_ENCABEZADO = ["Condición", " III 2014 - II 2015", " I 2015 - IV 2015",
               " II 2015 - I 2016", " I 2016 - IV 2016"]


def test_solo_toma_las_ventanas_de_ano_calendario():
    """Las móviles no son anuales. Estamparlas con un año sería inventar una
    correspondencia que el emisor no declara."""
    contenido = _libro([
        ["Banco Central de la República Dominicana"],
        _ENCABEZADO,
        ["Sector Informal", 51.31, 51.24, 51.00, 50.00],
        ["Ocupación Informal", 57.57, 57.46, 57.53, 57.68],
    ])
    assert parse_informality(contenido) == [(2015, 57.46), (2016, 57.68)]


def test_no_confunde_ocupacion_informal_con_sector_informal():
    """Miden cosas distintas y corren ~6 puntos separadas: tomar la fila equivocada
    cambiaría el nivel de la serie sin que nada lo advirtiera."""
    contenido = _libro([
        _ENCABEZADO,
        ["Sector Informal", 51.31, 51.24, 51.00, 50.00],
        ["Ocupación Informal", 57.57, 57.46, 57.53, 57.68],
    ])
    assert [v for _y, v in parse_informality(contenido)] == [57.46, 57.68]
    assert [v for _y, v in parse_informality(contenido, label="Sector Informal")] == [51.24, 50.00]


def test_la_hoja_correcta_es_la_de_promedios_no_la_primera():
    """El libro trae la serie trimestral en 'Indicadores' y la anual en la de
    promedios. Leer la primera hoja daría una serie con el período equivocado."""
    contenido = _libro([_ENCABEZADO, ["Ocupación Informal", 1.0, 57.46, 2.0, 57.68]])
    assert parse_informality(contenido) == [(2015, 57.46), (2016, 57.68)]


def test_layout_cambiado_levanta_con_el_motivo():
    sin_ventanas = _libro([["Condición", "2015", "2016"],
                           ["Ocupación Informal", 57.46, 57.68]])
    with pytest.raises(BcrdLaborUnavailable, match="año calendario"):
        parse_informality(sin_ventanas)

    sin_fila = _libro([_ENCABEZADO, ["Otra cosa", 1, 2, 3, 4]])
    with pytest.raises(BcrdLaborUnavailable, match="no se encontró la fila"):
        parse_informality(sin_fila)

    with pytest.raises(BcrdLaborUnavailable, match="no trae la hoja"):
        parse_informality(_libro([_ENCABEZADO], hoja="Otra Hoja"))


def test_valores_fuera_de_rango_se_descartan_no_se_recortan():
    """Una tasa no puede ser 0 ni >100. Un valor así es un artefacto de lectura, y
    recortarlo lo disfrazaría de dato bueno."""
    contenido = _libro([
        _ENCABEZADO,
        ["Ocupación Informal", 57.57, 0, 57.53, 145.0],
    ])
    with pytest.raises(BcrdLaborUnavailable, match="rango"):
        parse_informality(contenido)


def test_la_etiqueta_por_defecto_es_la_del_empleo():
    assert INFORMALITY_LABEL == "ocupacion informal"
