"""El conector del OC-SENI: lo que la API hace en silencio y lo que la hoja puede tener corrido.

Tres trampas verificadas contra la fuente real (2026-09-07 y 2026-09-14), cada una con su test:

* un área inexistente devuelve **200 con []**: fuera de la lista blanca se lanza;
* la hoja «Iny» trae **dos bloques de año** y el orden se verifica contra la variación que el
  propio OC publica: con los años cruzados, el parseo falla;
* los meses posteriores a la edición vienen vacíos o en cero: **no se leen**.

Corre sin red: el fixture es la hoja «Iny» real de la edición del 20 de agosto de 2026.
"""
from datetime import date

import openpyxl
import pytest

from shared.data import oc_seni_client as oc
from shared.data.base_client import _FIXTURES_DIR


def _filas_del_fixture():
    wb = openpyxl.load_workbook(_FIXTURES_DIR / oc.OCSENIClient.fixture_file, read_only=True)
    try:
        return [list(f) for f in wb["Iny"].iter_rows(values_only=True)]
    finally:
        wb.close()


def _fila_de(filas, etiqueta, desde=0):
    for i in range(desde, len(filas)):
        celdas = [v for v in filas[i][:2] if v not in (None, "")]
        if celdas and oc._norm(celdas[0]).startswith(etiqueta):
            return i
    raise AssertionError(f"el fixture no trae la fila {etiqueta!r}")


def _cabeceras(filas):
    return [i for i, f in enumerate(filas)
            if sum(1 for v in f if v is not None and oc._norm(v) in oc._MESES) == 12]


# ── La lista blanca de áreas ──────────────────────────────────────────────────────

@pytest.mark.parametrize("area", [
    "Transacciones Económicas y Cálculos Comerciales",     # con espacios: la API da 500
    "Transacciones-Economicas-y-Calculos-Comerciales",     # sin tildes: la API da 200 con []
    "Informe-Mensual-de-Transacciones-Económicas",
])
def test_un_area_FUERA_de_la_lista_blanca_falla_RUIDOSAMENTE_antes_de_pedir(area, monkeypatch):
    import httpx

    def no_debe_pedir(*a, **k):
        raise AssertionError("se pidió a la red un área que no está en la lista blanca")

    monkeypatch.setattr(httpx.Client, "get", no_debe_pedir)
    with pytest.raises(oc.AreaDesconocida, match="200 con \\[\\]"):
        oc.OCSENIClient(mode="live").listar(area)


def test_el_area_del_IMTE_va_con_guiones_y_tildes_codificadas():
    url = oc.url_del_listado(oc.AREA_TRANSACCIONES)
    assert url.endswith("/Transacciones-Econ%C3%B3micas-y-C%C3%A1lculos-Comerciales?loggedIn=false")


# ── El parseo de la hoja ──────────────────────────────────────────────────────────

def test_el_fixture_se_lee_con_el_orden_VERIFICADO_y_hasta_el_mes_de_la_edicion():
    registros, edicion = oc.OCSENIClient(mode="fixture").leer_ultima_edicion()
    assert edicion.periodo == "2026-07" and edicion.publicada == date(2026, 8, 20)
    por_serie = {}
    for r in registros:
        por_serie.setdefault(r.series, {})[r.period] = r.value
    iny = por_serie[oc.SERIE_INYECCIONES]
    assert min(iny) == "2025-01" and max(iny) == "2026-07"
    assert "2026-08" not in iny, "un mes posterior a la edición se leyó como medición"
    # Cifras de la hoja, no transcritas: la de enero cierra contra la variación que publica el OC.
    assert iny["2026-01"] / iny["2025-12"] - 1 == pytest.approx(-0.05720088453845984, abs=1e-9)
    perdidas = por_serie[oc.SERIE_PERDIDAS]["2026-01"]
    retiros = por_serie[oc.SERIE_RETIROS]["2026-01"]
    assert perdidas == pytest.approx((iny["2026-01"] - retiros) / iny["2026-01"] * 100, abs=1e-6), (
        "«% Pérdidas Totales» dejó de ser (inyecciones − retiros) / inyecciones")
    assert {r.unit for r in registros if r.series == oc.SERIE_PERDIDAS} == {"%"}


def test_con_un_año_que_NO_CIERRA_con_la_variacion_publicada_el_parseo_FALLA():
    """El caso que importa: los dos valores existen y no cierran con la cifra del OC. Es lo que
    pasaría con los bloques cruzados en una edición de diciembre, con los dos años completos."""
    filas = _filas_del_fixture()
    _, anterior = _cabeceras(filas)
    i = _fila_de(filas, "inyecciones", anterior)
    col_dic = next(j for j, v in enumerate(filas[anterior]) if v is not None and oc._norm(v) == "dic")
    filas[i] = list(filas[i])
    filas[i][col_dic] = filas[i][col_dic] * 1.02
    with pytest.raises(oc.EstructuraInesperada, match="orden verificado"):
        oc.parse_hoja_iny(filas, 2026, "2026-07")


def test_con_los_bloques_CRUZADOS_en_una_edicion_parcial_tambien_falla():
    """En una edición de julio el año en curso no tiene diciembre: cruzado, no hay con qué
    verificar. Falla igual — nunca se publica un orden que no se pudo comprobar."""
    filas = _filas_del_fixture()
    actual, anterior = _cabeceras(filas)
    fila_actual = _fila_de(filas, "inyecciones", actual)
    fila_anterior = _fila_de(filas, "inyecciones", anterior)
    filas[fila_actual], filas[fila_anterior] = filas[fila_anterior], filas[fila_actual]
    with pytest.raises(oc.EstructuraInesperada, match="verificar el orden"):
        oc.parse_hoja_iny(filas, 2026, "2026-07")


def test_sin_la_VARIACION_publicada_no_hay_con_que_verificar_y_falla():
    filas = _filas_del_fixture()
    del filas[_fila_de(filas, "variacion")]
    with pytest.raises(oc.EstructuraInesperada):
        oc.parse_hoja_iny(filas, 2026, "2026-07")


def test_un_TERCER_bloque_de_meses_no_se_adivina():
    filas = _filas_del_fixture()
    filas.append(list(filas[_cabeceras(filas)[0]]))
    with pytest.raises(oc.EstructuraInesperada, match="3 bloques"):
        oc.parse_hoja_iny(filas, 2026, "2026-07")


def test_una_celda_de_TEXTO_no_es_una_cifra():
    filas = _filas_del_fixture()
    actual = _cabeceras(filas)[0]
    i = _fila_de(filas, "retiros totales", actual)
    filas[i] = list(filas[i])
    filas[i][3] = "n/d"                      # la columna de FEB
    series = oc.parse_hoja_iny(filas, 2026, "2026-07")
    assert series[oc.SERIE_RETIROS]["2026-02"] is None


# ── El listado ────────────────────────────────────────────────────────────────────

def _item(nombre, ruta, publicada="2026-08-20T15:00:00Z", id_="x"):
    return {"id": id_, "nombre_archivo": nombre, "ruta": ruta, "fecha_publicacion": publicada}


def test_el_mes_sale_de_la_RUTA_y_gana_la_version_mas_alta():
    ruta = "//Informe Mensual de Transacciones Económicas/2026/07. Jul/Versión {v}"
    listado = [
        _item("OC-GC-07-IMTE-20260820-V0.zip", ruta.format(v=0), id_="v0"),
        _item("OC-GC-07-IMTE-20260903-V1.zip", ruta.format(v=1), "2026-09-03T12:00:00Z", "v1"),
        _item("OC-GC-07-IMTE-20231219-V0.pdf", "//Informe Mensual/2023/11. Nov/Versión 0"),
        _item("CMGBenvio_14_Septiembre_2022.zip", "//Costos Marginales/2022/09. Sep/14/Versión 0"),
    ]
    eds = oc.ediciones_imte(listado)
    assert [(e.periodo, e.file_id, e.publicada) for e in eds] == [
        ("2026-07", "v1", date(2026, 9, 3))]


def test_fetch_cumple_el_contrato_de_SourceClient_y_filtra():
    cliente = oc.OCSENIClient(mode="fixture")
    julio = cliente.fetch(series=oc.SERIE_PERDIDAS, period="2026-07")
    assert [(r.series, r.period) for r in julio] == [(oc.SERIE_PERDIDAS, "2026-07")]
