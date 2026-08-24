"""La serie COFOG de Hacienda — indicador 2.33 de la END.

Las filas de acá son REALES: se capturaron de la hoja del emisor el 2026-08-24, con sus
fracciones, sus asteriscos de preliminar y sus tres filas que nombran el universo. Un fixture
inventado no habría reproducido el defecto que rompió la primera versión de este lector.
"""
import pytest

from shared.data.digepres_funcional import DOCUMENTOS
from shared.data.hacienda_cofog import (BANDA_PCT_PIB, CofogError, GastoFuncional, anio_de,
                                        es_preliminar, fila_de_salud, leer_hojas, verificar)

#: Las filas que importan de la hoja «Anual % PIB», en su orden real. Tres nombran el
#: universo —título, subtítulo y encabezado— y solo la tercera trae los años.
TITULO = ["Clasificación de las Erogaciones por Funciones  del Gobierno Central Presupuestario "]
UNIDAD = ["% del Producto Interno Bruto"]
ENCABEZADO = ["Gobierno Central Presupuestario  1/", 2008.0, 2009.0, 2010.0, 2015.0,
              2020.0, "2021*", "2025*"]
SALUD = ["7.0.7 Salud", 0.013797265806367464, 0.013599925536634059, 0.01705976747342457,
         0.018320, 0.022950, 0.024040, 0.018550]
SUBFUNCION = ["7.0.7.1 Productos, útiles y equipos médicos", 0.001, 0.001, 0.001, 0.001,
              0.001, 0.001, 0.001]

HOJA = [TITULO, UNIDAD, ENCABEZADO, SUBFUNCION, SALUD]

MONTOS = [["Gobierno Central Presupuestario  1/", 2008.0, 2009.0, 2010.0, 2015.0,
           2020.0, "2021*", "2025*"],
          ["7.0.7 Salud", 22926.1, 23610.0, 33833.0, 56790.8, 102274.7, 129640.4, 146518.7]]


class TestElEncabezadoQueTraeLosANIOS:
    def test_no_se_toma_la_PRIMERA_fila_que_nombra_el_universo(self):
        """El defecto que rompió la primera versión: tres filas nombran el universo y la
        primera es el TÍTULO, que no trae ningún año. Es el mismo error que tomar la primera
        columna «%PIB» de un cuadro que trae dos."""
        assert TITULO[0].count("Gobierno Central Presupuestario") == 1
        serie = leer_hojas(HOJA)
        assert [g.anio for g in serie] == [2008, 2009, 2010, 2015, 2020, 2021, 2025]

    def test_sin_ninguna_fila_de_anios_LEVANTA(self):
        with pytest.raises(CofogError, match="serie de años"):
            leer_hojas([TITULO, UNIDAD, ["Gobierno Central Presupuestario", "a", "b"],
                        ["7.0.7 Salud", 0.01, 0.01]])

    def test_sin_el_universo_declarado_LEVANTA(self):
        """El sujeto se exige de la hoja: el emisor publica otros agregados con la misma
        forma, y leer el equivocado no rompe nada — cambia de quién se habla."""
        anonima = [["Serie histórica"], ENCABEZADO[1:], SALUD]
        with pytest.raises(CofogError, match="GOBIERNO CENTRAL PRESUPUESTARIO"):
            leer_hojas(anonima)


class TestQueFilaEsSalud:
    def test_exige_el_CODIGO_y_no_solo_la_palabra(self):
        """`7.0.7.1 Productos médicos` también dice Salud en su rama y mide una PARTE."""
        assert fila_de_salud([f[0] for f in HOJA]) == HOJA.index(SALUD)

    def test_la_subfuncion_NO_se_confunde_con_el_total(self):
        serie = leer_hojas(HOJA)
        assert serie[1].pct_pib == pytest.approx(1.360, abs=0.001)

    def test_sin_fila_de_salud_LEVANTA(self):
        with pytest.raises(CofogError, match="Salud"):
            leer_hojas([TITULO, ENCABEZADO, ["7.0.8 Actividades recreativas", 0.01]])


class TestLaEscalaYLaSALVEDAD:
    def test_la_hoja_guarda_FRACCION_y_se_sirve_porcentaje(self):
        serie = {g.anio: g.pct_pib for g in leer_hojas(HOJA)}
        assert serie[2009] == pytest.approx(1.360, abs=0.001)
        assert serie[2020] == pytest.approx(2.295, abs=0.001)

    def test_la_banda_ataja_el_error_de_ESCALA(self):
        """Si el emisor pasara a publicar porcentaje y siguiéramos multiplicando por cien,
        la serie saldría cien veces corrida y perfectamente creíble en su forma."""
        with pytest.raises(CofogError, match="fuera de la banda"):
            verificar(136.0, 2009)
        with pytest.raises(CofogError, match="fuera de la banda"):
            verificar(BANDA_PCT_PIB[0] / 2, 2009)

    def test_el_asterisco_de_PRELIMINAR_viaja_con_el_dato(self):
        """«Preliminar» y «definitivo» no sostienen la misma afirmación, y 2025 —que es una
        META de la ley— es de los preliminares."""
        serie = {g.anio: g for g in leer_hojas(HOJA)}
        assert serie[2020].preliminar is False
        assert serie[2021].preliminar is True and serie[2025].preliminar is True

    def test_el_lector_del_asterisco_no_depende_del_tipo_de_celda(self):
        """El emisor mezcla números y texto en la misma fila: 2008.0 y «2021*»."""
        assert anio_de(2008.0) == 2008 and es_preliminar(2008.0) is False
        assert anio_de("2021*") == 2021 and es_preliminar("2021*") is True
        assert anio_de("Gobierno Central Presupuestario  1/") is None


def test_el_monto_viaja_al_lado_de_la_razon():
    serie = {g.anio: g for g in leer_hojas(HOJA, MONTOS)}
    assert serie[2009].monto_mm_rd == pytest.approx(23610.0)
    assert serie[2025].monto_mm_rd == pytest.approx(146518.7)


def test_sin_hoja_de_montos_la_serie_igual_sale():
    serie = leer_hojas(HOJA)
    assert all(g.monto_mm_rd is None for g in serie)
    assert len(serie) == 7


def test_CRUZA_con_la_lectura_de_los_PDF_de_DIGEPRES():
    """Las dos vías tienen que dar lo mismo, y por eso se conservan las dos.

    Son dos lecturas independientes de dos documentos distintos del mismo Estado: la hoja de
    Hacienda y el cuadro funcional de los informes de DIGEPRES. Que cierren entre sí es la
    comprobación más fuerte que este indicador va a tener, y si un día dejan de cerrar, lo
    que hay que revisar es el lector — no elegir la que convenga.
    """
    de_digepres = {2009: 1.357, 2010: 1.684}          # medidos el 2026-08-24
    de_hacienda = {g.anio: g.pct_pib for g in leer_hojas(HOJA)}
    for anio, esperado in de_digepres.items():
        assert abs(de_hacienda[anio] - esperado) / esperado * 100 < 2.0, (
            f"{anio}: Hacienda da {de_hacienda[anio]} y DIGEPRES {esperado}; una de las dos "
            f"lecturas está mal y da igual cuál")


def test_COFOG_cubre_los_anios_que_a_DIGEPRES_le_FALTAN():
    """2020 y 2025 son metas de la ley y no están en ningún informe de DIGEPRES. Que esta
    fuente los traiga es la razón por la que pasa a ser la vía principal."""
    anios_cofog = {g.anio for g in leer_hojas(HOJA)}
    assert {2020, 2025} <= anios_cofog
    assert not {2020, 2025} & set(DOCUMENTOS)


def test_el_dataclass_declara_lo_que_hace_falta_para_afirmar():
    g = GastoFuncional(anio=2025, pct_pib=1.855, monto_mm_rd=146518.7, preliminar=True)
    assert (g.anio, g.preliminar) == (2025, True)
