"""El CNZFE por su Informe Estadístico cuando datos.gob.do no entrega el CSV (2026-09-15).

El portal lista los recursos del CNZFE y su descarga responde HTTP 500. El mismo cuadro viene
en el PDF anual del CNZFE. Estos tests fijan tres cosas: que el PDF se lee igual que el CSV,
que ante un cambio de forma la lectura FALLA en vez de correr columnas, y que el resultado
dice de dónde salió el dato. Nunca tocan la red.
"""
import pathlib
import ssl

import pytest

from shared.data import cnzfe_client as cz

_FIXTURE = pathlib.Path(cz.__file__).parent / "fixtures" / "cnzfe_informe_2025_cuadro_1.txt"

#: Las filas 2021-2024 del CSV que el portal servía (las mismas de test_free_zones).
_CSV = (
    "\ufeffAño,Total parques aprobados,Total empresas operando,Total de empleos,"
    "Exportaciones (millones US$),Inversion total acumulada (millones US$),"
    "Gastos operativos locales (millones US$),Salarios operarios semanales (RD$),"
    "Salarios tecnicos semanales (RD$),Areas de naves ocupadas (pies cuadrados)\n"
    "2021,79,734,183232,7179.6,5903.1,1944.3,3646.83,6388.53,42452389.5\n"
    "2022,84,774,192461,7827.3,7160.9,1993.9,4222.61,7032.88,47488229.3\n"
    "2023,87,820,198034,7959.4,7496.2,2027.8,4628.53,7573.56,49171262.07\n"
    "2024,94,843,198552,8500.3,7735.7,2163.9,4879.08,8236.75,50679794.32\n"
)


def _texto() -> str:
    return _FIXTURE.read_text(encoding="utf-8")


def test_el_cuadro_1_trae_los_veinte_anios_con_sus_nueve_columnas():
    v = cz.parse_cuadro_1(_texto())
    assert sorted(v) == list(range(2006, 2026))
    assert v[2025] == {"parks": 98, "companies": 858, "jobs": 200237, "exports_musd": 8548.6,
                       "investment_musd": 8169.8, "local_spend_musd": 2175.7,
                       "wage_operator_rd": 5202.02, "wage_technician_rd": 8935.15,
                       "occupied_area_sqft": 51759000.5}


def test_el_pdf_y_el_csv_dicen_lo_mismo_en_los_anios_que_comparten():
    pdf, csv = cz.parse_cuadro_1(_texto()), cz.parse_free_zone_vars(_CSV)
    for anio, campos in csv.items():
        assert set(campos) == set(pdf[anio]), anio
        for campo, valor in campos.items():
            assert pdf[anio][campo] == pytest.approx(valor, abs=0.06), (anio, campo)


def test_una_columna_que_falta_hace_fallar_la_lectura():
    texto = _texto().replace("Gastos locales", "Otra cosa")
    with pytest.raises(RuntimeError, match="gastos locales"):
        cz.parse_cuadro_1(texto)


def test_una_celda_vacia_falla_en_vez_de_correr_las_columnas():
    texto = _texto()
    assert "2025 98 858 " in texto
    with pytest.raises(RuntimeError, match="2025"):
        cz.parse_cuadro_1(texto.replace("2025 98 858 ", "2025 858 "))


def test_se_elige_el_informe_mas_reciente():
    html = ('<a href="https://cnzfe.gob.do/wp-content/uploads/2026/06/Informe-Estadistico-2025.pdf">'
            '<a href="https://cnzfe.gob.do/wp-content/uploads/2025/06/Informe-Estadistico-2024.pdf">')
    assert cz.ultimo_informe(html) == (
        2025, "https://cnzfe.gob.do/wp-content/uploads/2026/06/Informe-Estadistico-2025.pdf")
    with pytest.raises(RuntimeError):
        cz.ultimo_informe("<html></html>")


def test_un_500_del_portal_no_se_lee_como_csv(monkeypatch):
    c = cz.CNZFEClient()
    monkeypatch.setattr(c, "_resolve_csv", lambda slug: "https://datos.gob.do/x.csv")
    monkeypatch.setattr(c, "_descargar",
                        lambda url: (500, "text/html; charset=utf-8", b"<!DOCTYPE html>"))
    with pytest.raises(RuntimeError, match="HTTP 500"):
        c._fetch_csv(cz.SLUG_VARS)


def test_si_el_portal_falla_se_lee_el_informe_y_se_dice_de_donde_salio(monkeypatch):
    c = cz.CNZFEClient()

    def falla(slug):
        raise RuntimeError("CNZFE: el recurso CSV respondió HTTP 500")

    monkeypatch.setattr(c, "_fetch_csv", falla)
    monkeypatch.setattr(cz.cnzfe_informe_client, "free_zone_vars",
                        lambda: cz.parse_cuadro_1(_texto()))
    v = c.free_zone_vars()
    assert v[2025]["jobs"] == 200237
    assert "Informe Estadístico" in c.ultimo_origen and "HTTP 500" in c.ultimo_origen


def test_con_el_csv_disponible_no_se_baja_el_pdf(monkeypatch):
    c = cz.CNZFEClient()
    monkeypatch.setattr(c, "_fetch_csv", lambda slug: _CSV)

    def no_debe_llamarse():
        raise AssertionError("bajó el PDF con el CSV disponible")

    monkeypatch.setattr(cz.cnzfe_informe_client, "free_zone_vars", no_debe_llamarse)
    assert sorted(c.free_zone_vars()) == [2021, 2022, 2023, 2024]
    assert c.ultimo_origen.startswith("datos.gob.do")


def test_la_conexion_a_cnzfe_verifica_tls_con_el_intermedio_fijado():
    ctx = cz.cnzfe_informe_client._ssl()
    assert ctx.verify_mode == ssl.CERT_REQUIRED and ctx.check_hostname
    sujetos = [dict(x[0] for x in cert["subject"]).get("commonName") for cert in ctx.get_ca_certs()]
    assert "SSL.com TLS Transit ECC CA R2" in sujetos
