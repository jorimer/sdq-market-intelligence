"""El aporte del Gobierno a las distribuidoras — indicador 3.30 de la END.

Las filas son REALES, del anexo de diciembre de 2020: la etiqueta en la SEGUNDA columna, doce
meses más el acumulado, y el bloque del total conviviendo con los de las tres distribuidoras.
El módulo declaraba este indicador como brecha —«la hoja no tiene cabecera de años»— y la
conclusión estaba mal: la hoja no tiene años porque sus columnas son MESES, y el año viene del
anexo que se abrió.
"""
import pytest

from shared.data.mem_client import (FILA_APORTES, MEMUnavailable, acumulado_de,
                                    aporte_del_gobierno)


def _fila(rotulo, meses, acumulado=None):
    """Como las devuelve el anexo: primera columna VACÍA y la etiqueta en la segunda."""
    return [None, rotulo] + list(meses) + [sum(meses) if acumulado is None else acumulado]


#: 2020, filas REALES del anexo de diciembre. Las tres distribuidoras suman el total al
#: peso: 217,63 + 148,61 + 212,35 = 578,59. Esa es la identidad que dice cuál es cuál.
TOTAL = _fila("Aportes del gobierno",
              [59.4605, 59.3848, 59.0188, 58.8927, 58.7034, 58.5267, 58.3254,
               33.2553, 33.2553, 33.2553, 33.2553, 33.2553], acumulado=578.5889)
ESTE = _fila("Aportes del gobierno",
             [22.3947, 22.3661, 22.2279, 22.1802, 22.1087, 22.042, 21.9662,
              12.469, 12.469, 12.469, 12.469, 12.469], acumulado=217.6307)
NORTE = _fila("Aportes del gobierno",
              [15.4556, 15.4339, 15.3292, 15.2931, 15.2389, 15.1883, 15.1306,
               8.3082, 8.3082, 8.3082, 8.3082, 8.3082], acumulado=148.6103)
SUR = _fila("Aportes del gobierno",
            [21.6102, 21.5848, 21.4618, 21.4194, 21.3558, 21.2965, 21.2286,
             12.4782, 12.4782, 12.4782, 12.4782, 12.4782], acumulado=212.348)
#: Otro bloque del MISMO anexo con la misma etiqueta —y otra capitalización—. No cierra la
#: identidad contra ninguna terna, así que la aritmética lo descarta sola.
OTRO_BLOQUE = _fila("Aportes del Gobierno",
                    [6.2356, 6.2356, 6.2356, 6.2356, 6.2356, 12.4782, 6.2356,
                     6.2356, 6.2356, 6.2356, 6.2356, 6.2356], acumulado=81.0703)
#: Otro CONCEPTO del mismo anexo. Un `in` lo confundiría con el aporte.
INVERSION = _fila("Aportes del Gobierno para Inversión", [30.8] * 12)
DEFICIT = _fila("Cubrir Déficit Operacional ", [33.25533333] * 12)


class TestElAcumuladoSeCOMPRUEBA:
    def test_es_la_suma_de_los_doce_meses(self):
        assert acumulado_de(TOTAL) == pytest.approx(578.589, abs=0.01)

    def test_una_ultima_columna_que_NO_es_la_suma_LEVANTA(self):
        """No se toma «la última» por ser la última. Si el emisor agregara una variación o
        una proyección al final, la identidad deja de cerrar y esto para."""
        con_variacion = _fila("Aportes del gobierno", [10.0] * 12, acumulado=999.0)
        with pytest.raises(MEMUnavailable, match="no es la suma"):
            acumulado_de(con_variacion)

    def test_una_fila_corta_LEVANTA_en_vez_de_inventar(self):
        with pytest.raises(MEMUnavailable, match="identidad"):
            acumulado_de([None, "Aportes del gobierno", 1.0, 2.0])


class TestCualDeLosBLOQUES:
    def test_el_total_lo_dice_la_ARITMETICA_no_la_posicion(self):
        """La etiqueta aparece cinco veces en el anexo de 2020. El total es el único cuyo
        acumulado equivale a la suma de otros tres. Elegir «el primero» habría funcionado hoy
        y sería una posición disfrazada de regla."""
        filas = [ESTE, TOTAL, NORTE, OTRO_BLOQUE, INVERSION, SUR]   # desordenadas
        assert aporte_del_gobierno(filas) == pytest.approx(578.589, abs=0.01)

    def test_NO_confunde_el_aporte_para_INVERSION(self):
        assert FILA_APORTES == "APORTES DEL GOBIERNO"
        solo_inversion = [INVERSION, INVERSION, INVERSION, INVERSION]
        with pytest.raises(MEMUnavailable, match="ninguna fila"):
            aporte_del_gobierno(solo_inversion)

    def test_sin_bloque_de_total_LEVANTA(self):
        """Si el emisor dejara de publicar el agregado, servir una distribuidora sola sería
        publicar un tercio del subsidio contra la meta del país."""
        with pytest.raises(MEMUnavailable, match="suma de otras tres"):
            aporte_del_gobierno([ESTE, NORTE, SUR])

    def test_la_etiqueta_se_lee_del_primer_TEXTO_no_de_la_primera_celda(self):
        """El cuadro tiene la primera columna vacía. Leer `fila[0]` devolvía vacío para todas
        y el lector no encontraba ninguna fila — que fue exactamente lo que pasó."""
        assert TOTAL[0] is None and isinstance(TOTAL[1], str)
        assert aporte_del_gobierno([ESTE, TOTAL, NORTE, SUR]) == pytest.approx(578.589, abs=0.01)


def test_el_DEFICIT_operacional_no_es_el_aporte():
    """Es un componente del aporte, no el aporte. En 2020 son 399,06 de 578,59; en 2025
    coinciden, y confiar en esa coincidencia sería atarse a un año."""
    with pytest.raises(MEMUnavailable, match="ninguna fila"):
        aporte_del_gobierno([DEFICIT, DEFICIT, DEFICIT, DEFICIT])


def test_CONTRA_LA_LEY_la_meta_de_2020_esta_incumplida_por_un_orden_de_magnitud():
    """La ley fija 70,0 millones de US$ para 2020 y el anexo da 578,6."""
    observado = aporte_del_gobierno([ESTE, TOTAL, NORTE, SUR])
    assert observado / 70.0 > 8.0
