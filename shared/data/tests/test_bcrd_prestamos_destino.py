"""Préstamos por destino (BCRD) — indicador 3.24 de la END.

La estructura es REAL: tres perímetros apilados en la misma hoja con el mismo formato
interno, y la fila consolidada conviviendo con sus destinos. Este módulo existe porque el
motivo de descarte del 3.24 citaba ocho cifras que nadie podía recomputar.
"""
import datetime as dt

import pytest

from shared.data.bcrd_prestamos_destino import (DESTINOS_BIENES, FILA_CONSOLIDADA,
                                                PERIMETRO_DEL_324, PERIMETROS,
                                                PrestamosError, bloques_de,
                                                columnas_de_diciembre, es_productivo, monto,
                                                razon_de_ventana)

DESTINOS = ["            AGRICULTURA, SILVICULTURA Y PESCA (4)",
            "            EXPLOTACIÓN DE MINAS Y CANTERAS",
            "            INDUSTRIAS MANUFACTURERAS",
            "            ELECTRICIDAD, GAS Y AGUA",
            "            CONSTRUCCIÓN",
            "            COMERCIO AL POR MAYOR Y AL POR MENOR",
            "            ADQUISICIÓN DE VIVIENDAS",
            "            PRÉSTAMOS DE CONSUMO",
            "            RESTO DE OTRAS ACTIVIDADES (3)"]


def _bloque(titulo, valores):
    """Un perímetro con dos diciembres, como los apila el emisor."""
    filas = [[titulo] + [None] * 2,
             ["SECTOR", dt.datetime(2005, 12, 1), dt.datetime(2006, 12, 1)],
             ["    SECTOR PRIVADO M/N", 0, 0],
             [FILA_CONSOLIDADA, sum(valores), sum(valores)]]
    filas += [[d, v, v] for d, v in zip(DESTINOS, valores)]
    filas.append(["En millones RD$", None, None])
    return filas


#: Banca múltiple y consolidado difieren: el segundo incluye cooperativas y financieras
#: públicas, y por eso da más.
BM = [100.0, 10.0, 200.0, 20.0, 70.0, 300.0, 150.0, 400.0, 90.0]
CONSOL = [130.0, 12.0, 240.0, 24.0, 90.0, 360.0, 190.0, 460.0, 110.0]
HOJA = (_bloque("ESTADÍSTICAS: PRÉSTAMOS POR DESTINO DE LAS OTRAS SOCIEDADES DE "
                "DEPÓSITOS (CONSOLIDADO)", CONSOL)
        + _bloque("ESTADÍSTICAS: PRÉSTAMOS POR DESTINO Y MONEDA (BANCOS MÚLTIPLES)", BM)
        + _bloque("ESTADÍSTICAS: PRÉSTAMOS POR DESTINO Y MONEDA (RESTO DE LAS OSD)",
                  [c - b for c, b in zip(CONSOL, BM)]))
PIB = {2005: 10000.0, 2006: 10000.0}


class TestElPERIMETRO:
    def test_los_tres_se_ubican_por_su_TITULO_no_por_posicion(self):
        """Leer por índice fijo serviría el consolidado creyendo leer la banca múltiple."""
        b = bloques_de(HOJA)
        assert set(b) == set(PERIMETROS)
        assert b["banca_multiple"].fila_encabezado < b["resto_osd"].fila_encabezado

    def test_el_perimetro_CAMBIA_el_resultado(self):
        """Es la razón por la que hay que nombrarlo: el 5to Informe declara banca múltiple."""
        b = bloques_de(HOJA)
        bm = razon_de_ventana(HOJA, b["banca_multiple"], PIB, [2005, 2006])
        cons = razon_de_ventana(HOJA, b["consolidado"], PIB, [2005, 2006])
        assert cons > bm > 0
        assert PERIMETRO_DEL_324 == "banca_multiple"

    def test_si_falta_un_perimetro_LEVANTA(self):
        solo_uno = _bloque("PRÉSTAMOS POR DESTINO Y MONEDA (BANCOS MÚLTIPLES)", BM)
        with pytest.raises(PrestamosError, match="perímetros"):
            bloques_de(solo_uno)


class TestQueSeSUMA:
    def test_la_fila_consolidada_NO_se_suma_con_sus_destinos(self):
        """Sería contar cada préstamo dos veces."""
        b = bloques_de(HOJA)["banca_multiple"]
        assert FILA_CONSOLIDADA not in b.destinos

    def test_productivo_se_define_por_EXCLUSION(self):
        """La ley dice «producción de bienes Y servicios»: el comercio es un servicio."""
        assert es_productivo("COMERCIO AL POR MAYOR Y AL POR MENOR")
        assert not es_productivo("PRÉSTAMOS DE CONSUMO")
        assert not es_productivo("ADQUISICIÓN DE VIVIENDAS")
        assert not es_productivo("RESTO DE OTRAS ACTIVIDADES (3)")

    def test_solo_bienes_es_un_subconjunto_de_los_productivos(self):
        b = bloques_de(HOJA)["banca_multiple"]
        col = columnas_de_diciembre(HOJA[b.fila_encabezado])[2005]
        assert monto(HOJA, b, col, DESTINOS_BIENES) < monto(HOJA, b, col)

    def test_un_destino_que_no_existe_LEVANTA(self):
        b = bloques_de(HOJA)["banca_multiple"]
        col = columnas_de_diciembre(HOJA[b.fila_encabezado])[2005]
        with pytest.raises(PrestamosError, match="renombró"):
            monto(HOJA, b, col, ("PESCA DE ALTURA",))


class TestLaVENTANA:
    def test_solo_se_toman_los_cierres_de_DICIEMBRE(self):
        b = bloques_de(HOJA)["banca_multiple"]
        assert sorted(columnas_de_diciembre(HOJA[b.fila_encabezado])) == [2005, 2006]

    def test_una_ventana_INCOMPLETA_levanta_en_vez_de_promediar_lo_que_hay(self):
        """La ley promedia 2005-2010. Promediar los años que existan daría un número
        parecido al que pide sin serlo — es la regla que mató la hipótesis del 3.14."""
        b = bloques_de(HOJA)["banca_multiple"]
        with pytest.raises(PrestamosError, match="incompleta"):
            razon_de_ventana(HOJA, b, PIB, [2005, 2006, 2007])

    def test_la_razon_es_el_promedio_de_los_anios_de_la_ventana(self):
        b = bloques_de(HOJA)["banca_multiple"]
        # productivos = todo menos vivienda (150), consumo (400) y resto (90)
        esperado = (100 + 10 + 200 + 20 + 70 + 300) / 10000 * 100
        assert razon_de_ventana(HOJA, b, PIB, [2005, 2006]) == pytest.approx(esperado, abs=0.01)
