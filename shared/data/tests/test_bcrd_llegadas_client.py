"""La llegada mensual de no residentes del BCRD: la columna se verifica contra la tasa publicada.

El fixture es la hoja real «No Residentes 78 - 26» de `lleg_total.xls` (subida al CDN el
2026-08-31), recortada a la cabecera y los bloques 2025-2026. Corre sin red.
"""
import copy

import openpyxl
import pytest

from shared.data import bcrd_llegadas_client as bl
from shared.data.base_client import _FIXTURES_DIR


def _filas():
    wb = openpyxl.load_workbook(_FIXTURES_DIR / bl.BCRDLlegadasClient.fixture_file, read_only=True)
    try:
        return [list(f) for f in wb.worksheets[0].iter_rows(values_only=True)]
    finally:
        wb.close()


def _col(filas, rotulo):
    for fila in filas[:10]:
        for j, v in enumerate(fila):
            if bl._norm(v or "") == rotulo:
                return j
    raise AssertionError(rotulo)


def test_el_fixture_se_lee_con_las_tres_columnas_VERIFICADAS():
    registros, edicion = bl.BCRDLlegadasClient(mode="fixture").leer_ultima_edicion()
    assert edicion.periodo == "2026-07"
    por = {}
    for r in registros:
        por.setdefault(r.series, {})[r.period] = r.value
    assert set(por) == {bl.SERIE_TOTAL, bl.SERIE_DOMINICANOS, bl.SERIE_EXTRANJEROS}
    total = por[bl.SERIE_TOTAL]
    assert min(total) == "2025-01" and max(total) == "2026-07"
    assert "2026-08" not in total, "un mes sin publicar se leyó"
    # Identidad del emisor: el total de no residentes es dominicanos + extranjeros.
    for periodo in ("2025-12", "2026-07"):
        assert total[periodo] == pytest.approx(
            por[bl.SERIE_DOMINICANOS][periodo] + por[bl.SERIE_EXTRANJEROS][periodo], rel=1e-9)
    assert {r.unit for r in registros} == {"personas"}


def test_con_las_columnas_de_dominicanos_y_extranjeros_CRUZADAS_el_parseo_FALLA():
    filas = copy.deepcopy(_filas())
    c_dom, c_ext = _col(filas, "dominicanos"), _col(filas, "extranjeros")
    for fila in filas[8:]:
        if len(fila) > c_ext:
            fila[c_dom], fila[c_ext] = fila[c_ext], fila[c_dom]
    with pytest.raises(bl.EstructuraInesperada, match="no es la verificada"):
        bl.parse_hoja_no_residentes(filas)


def test_sin_la_tasa_PUBLICADA_no_hay_con_que_verificar_y_falla():
    filas = copy.deepcopy(_filas())
    c_igual = _col(filas, "igual mes")
    for fila in filas[8:]:
        if len(fila) > c_igual:
            fila[c_igual] = None
    with pytest.raises(bl.EstructuraInesperada, match="tasa"):
        bl.parse_hoja_no_residentes(filas)


def test_sin_la_cabecera_de_grupos_no_se_adivina_la_columna():
    filas = [f for f in _filas() if not any(bl._norm(v or "") == "extranjeros" for v in f)]
    with pytest.raises(bl.EstructuraInesperada, match="cabecera"):
        bl.parse_hoja_no_residentes(filas)


def test_una_fila_de_mes_VACIA_no_se_lee_como_cero():
    """El BCRD puede dejar la fila del mes siguiente con las celdas vacías. Un cero ahí se
    publicaría como una caída del 100 % de las llegadas."""
    filas = copy.deepcopy(_filas())
    ultima = max(i for i, f in enumerate(filas) if f and bl._norm(f[0] or "") == "julio")
    filas.insert(ultima + 1, ["Agosto"] + [None] * (len(filas[ultima]) - 1))
    series = bl.parse_hoja_no_residentes(filas)
    assert "2026-08" not in series[bl.SERIE_TOTAL]
    assert max(series[bl.SERIE_TOTAL]) == "2026-07"


def test_un_guion_en_la_celda_no_es_una_cifra():
    assert bl._numero("-") is None and bl._numero("n.d.") is None and bl._numero(0.0) == 0.0


def test_fetch_cumple_el_contrato_y_filtra():
    julio = bl.BCRDLlegadasClient(mode="fixture").fetch(series=bl.SERIE_TOTAL, period="2026-07")
    assert [(r.series, r.period) for r in julio] == [(bl.SERIE_TOTAL, "2026-07")]
