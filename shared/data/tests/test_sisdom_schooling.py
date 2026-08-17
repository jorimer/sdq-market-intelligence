"""Escolaridad por región (SISDOM `05 3 007`) — lógica pura, sin red.

La planilla se arma con la forma REAL del cuadro, incluidas sus dos trampas: tres
regionalizaciones conviviendo en la misma hoja, y los años posteriores a 2016
asteriscados por el cambio de metodología ENFT→ENCFT.
"""
import io

import openpyxl
import pytest

from shared.data.sisdom_common import SisdomUnavailable
from shared.data.sisdom_schooling import SHEET, parse_schooling

REGIONES = ["Cibao Norte", "Cibao Sur", "Cibao Nordeste", "Cibao Noroeste", "Valdesia",
            "Enriquillo", "El Valle", "Yuma", "Higuamo", "Ozama o Metropolitana"]


def _libro(bloques, encabezado=None, hoja=SHEET):
    """*bloques* = [(título, [(rótulo, [valores…])])]."""
    wb = openpyxl.Workbook()
    wb.active.title = "otra"
    wb.active.append(["ruido"])
    ws = wb.create_sheet(hoja)
    ws.append(["SISTEMA DE INDICADORES SOCIALES"])
    ws.append(["Área Temática: Educación"])
    ws.append(encabezado or ["Desagregaciones", "2000", "2016", "2017*", "2024*"])
    for titulo, filas in bloques:
        ws.append([titulo])
        for rotulo, vals in filas:
            ws.append([rotulo, *vals])
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def _bloque(titulo, base=8.0):
    return (titulo, [(r, [base + i / 10, base + 1, base + 1.1, base + 1.2])
                     for i, r in enumerate(REGIONES)])


def test_extrae_las_diez_regiones_y_los_anos_asteriscados():
    """Descartar el asterisco corta la serie en 2016 y parece un problema de la fuente
    cuando es del parser — ya nos pasó una vez."""
    filas = parse_schooling(_libro([_bloque("Regiones de desarrollo (Decreto 710-04)")]))
    assert len({s for s, _y, _v in filas}) == 10
    assert sorted({y for _s, y, _v in filas}) == [2000, 2016, 2017, 2024]


def test_entre_regionalizaciones_compatibles_gana_la_de_mas_COBERTURA():
    """No la más reciente. Las dos traen las mismas diez regiones, así que preferir la
    nueva no aporta nada y cuesta historia: en el cuadro real, 345-22 arranca en 2016 y
    710-04 en 2000."""
    viejo = ("Regiones de desarrollo (Decreto 710-04)",
             [(r, [7.0, 8.0, 8.1, 8.2]) for r in REGIONES])          # 4 años
    nuevo = ("Regiones de desarrollo (Decreto 345-22)",
             [(r, [None, 9.0, 9.1, 9.2]) for r in REGIONES])         # 3 años
    filas = parse_schooling(_libro([viejo, nuevo]))
    assert 2000 in {y for _s, y, _v in filas}                        # ganó el de 710-04
    assert any(v == 7.0 for _s, _y, v in filas)


def test_la_regionalizacion_vieja_queda_excluida():
    """685-00 usa otro conjunto de regiones; mezclarla daría una serie incoherente."""
    solo_vieja = ("Regiones de desarrollo (Decreto 685-00)",
                  [("Región Valdesia", [7.0, 7.1, 7.2, 7.3])])
    with pytest.raises(SisdomUnavailable, match="ninguna es"):
        parse_schooling(_libro([solo_vieja]))


def test_un_panel_incompleto_levanta_en_vez_de_pasar():
    """Nueve regiones no son 'menos dato': el motor normaliza min-max ENTRE regiones, así
    que la décima faltante corre el mínimo o el máximo y cambia el score de las demás."""
    incompleto = ("Regiones de desarrollo (Decreto 710-04)",
                  [(r, [8.0, 8.1, 8.2, 8.3]) for r in REGIONES[:9]])
    with pytest.raises(SisdomUnavailable, match="9 de 10"):
        parse_schooling(_libro([incompleto]))


def test_valores_fuera_de_rango_se_descartan():
    """Una escolaridad media de 300 años es un artefacto de celda, no un dato."""
    raro = ("Regiones de desarrollo (Decreto 710-04)",
            [(r, [300.0, 8.1, 0, 8.3]) for r in REGIONES])
    filas = parse_schooling(_libro([raro]))
    assert sorted({y for _s, y, _v in filas}) == [2016, 2024]      # 2000 y 2017 fuera


def test_sin_bloque_regional_o_sin_hoja_levanta_con_el_motivo():
    with pytest.raises(SisdomUnavailable, match="no declara ningún bloque"):
        parse_schooling(_libro([("Sexo", [("Masculino", [8.0, 8.1, 8.2, 8.3])])]))
    with pytest.raises(SisdomUnavailable, match="no trae la hoja"):
        parse_schooling(_libro([_bloque("Regiones de desarrollo (Decreto 710-04)")],
                               hoja="99 9 999"))


def test_la_fila_TOTAL_es_la_cifra_nacional_y_no_una_region():
    """Encabeza «Desagregaciones», por encima de las tres regionalizaciones, y el parser la
    salteaba porque no resuelve a ninguna región. Es la misma historia que el `TOTAL PAIS`
    del tablero del MINERD: la cifra del país estaba en el archivo que ya bajábamos.

    Sin ella, quien compare contra una meta NACIONAL usa la de una región — con la
    escolaridad del indicador 2.18 de la END, 9,63 (cibao_norte) en vez de 9,59.
    """
    from shared.data.sisdom_schooling import COUNTRY_SLUG, parse_schooling

    # La fila «Total» va ANTES del bloque regional, tal como en el cuadro real.
    filas = parse_schooling(_libro(
        [("", [("Total", [9.5, 9.55, 9.57, 9.59])]),
         _bloque("Regiones de desarrollo (Decreto 710-04)")]))
    pais = sorted(f for f in filas if f[0] == COUNTRY_SLUG)
    assert pais == [(COUNTRY_SLUG, 2000, 9.5), (COUNTRY_SLUG, 2016, 9.55),
                    (COUNTRY_SLUG, 2017, 9.57), (COUNTRY_SLUG, 2024, 9.59)]
    # Y no se cuenta como una región más: el panel sigue teniendo las diez.
    regiones = {f[0] for f in filas if f[0] != COUNTRY_SLUG}
    assert len(regiones) == len(REGIONES)
