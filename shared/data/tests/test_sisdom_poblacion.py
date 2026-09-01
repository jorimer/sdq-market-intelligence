"""Población por región de desarrollo (SISDOM 02 3 009b). Offline (sin red).

El cuadro tiene la forma TRASPUESTA respecto del de ingreso: las regiones son FILAS y los
años COLUMNAS. Es la razón por la que este parser existe aparte y no reusa el de ingreso.
"""
import io

import openpyxl
import pytest

from shared.data.one_client import REGIONS
from shared.data.sisdom_poblacion import SHEET, SisdomUnavailable, parse_poblacion

_ETIQUETAS = [label for _slug, label in REGIONS]


def _libro(filas, sheet_name=SHEET, con_total=True):
    """Un libro con la forma real del cuadro: encabezado de años, bloque, Total, regiones."""
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = sheet_name
    ws.append(["SISTEMA DE INDICADORES SOCIALES"])
    ws.append(["Área Temática: Demografía"])
    ws.append(["Desagregaciones", "2024", "2025"])
    ws.append(["Regiones de Desarrollo (Ley 345-22)"])
    if con_total:
        ws.append(["Total", 10878267, 10954360])
    for fila in filas:
        ws.append(fila)
    ws.append(["Fuente: Elaborado por el VAES"])
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def _todas(base=400000):
    return [[etiqueta, base + i * 1000, base + i * 1000 + 500]
            for i, etiqueta in enumerate(_ETIQUETAS)]


def test_lee_las_diez_regiones_por_anio():
    filas = parse_poblacion(_libro(_todas()))
    assert len(filas) == len(REGIONS) * 2
    assert {slug for slug, _a, _v in filas} == {s for s, _l in REGIONS}
    assert {a for _s, a, _v in filas} == {2024, 2025}


def test_el_total_pais_no_entra_como_region():
    """La fila `Total` existe en el cuadro real. Colarla sería una undécima 'región' que
    aplasta a las diez de verdad en cualquier orden por tamaño."""
    filas = parse_poblacion(_libro(_todas()))
    assert all(slug in {s for s, _l in REGIONS} for slug, _a, _v in filas)
    assert max(v for _s, _a, v in filas) < 10_000_000


def test_un_panel_incompleto_falla_nombrando_lo_que_falta():
    """Nueve regiones no controlan a un score de diez: son universos distintos. Y el error
    dice CUÁL falta, para no tener que ir a mirar el Excel."""
    with pytest.raises(SisdomUnavailable, match="de 10 regiones"):
        parse_poblacion(_libro(_todas()[:-1]))


def test_sin_fila_de_anios_lo_dice_en_vez_de_devolver_vacio():
    """Vacío se lee como «el emisor no publica», que es otra cosa."""
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = SHEET
    ws.append(["Desagregaciones", "sin años acá"])
    for etiqueta in _ETIQUETAS:
        ws.append([etiqueta, 1])
    buf = io.BytesIO()
    wb.save(buf)
    with pytest.raises(SisdomUnavailable, match="fila de años"):
        parse_poblacion(buf.getvalue())


def test_una_celda_absurda_se_descarta_sin_tumbar_la_region():
    """Un artefacto de celda no es una población. Se descarta ese año, no la región."""
    slug_afectado = REGIONS[0][0]
    filas_crudas = _todas()
    filas_crudas[0][1] = 999_999_999          # basura en 2024 para la primera región
    filas = parse_poblacion(_libro(filas_crudas))
    anios = sorted(a for s, a, _v in filas if s == slug_afectado)
    assert anios == [2025], anios          # se cayó 2024, sobrevivió 2025
    assert len(filas) == len(REGIONS) * 2 - 1


def test_hoja_ausente_lo_dice_con_su_nombre():
    with pytest.raises(SisdomUnavailable, match="no trae la hoja"):
        parse_poblacion(_libro(_todas(), sheet_name="Otra"))
