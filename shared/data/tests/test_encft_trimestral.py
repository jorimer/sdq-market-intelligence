"""La ENCFT también se lee con la cadencia del EMISOR, no solo como promedio anual.

El caso. `parse_informality` lee la hoja «Promedio 4 Trimestres» —las ventanas anuales que
el propio BCRD calcula—, y esa serie sostiene los indicadores de la END, que son anuales.
Pero el crédito se mide por TRIMESTRE: leer el deterioro de una cartera contra un promedio
anual del mercado laboral compara dos cosas que no ocurrieron en la misma ventana. La serie
trimestral estaba publicada en otra hoja del MISMO libro que ya descargábamos.

Las dos conviven a propósito. La trimestral no se deriva de la anual ni al revés: promediar
cuatro trimestres para reproducir la anual daría un número que el BCRD no publicó.

Lo que estos tests fijan es lo que puede romperse en silencio: el TRIMESTRE se lee del
numeral romano y nunca de la posición —el libro arranca en III-2014, así que numerar por
orden etiquetaría III como I—, y la etiqueta se compara EXACTO tras quitarle la marca de
nota al pie, porque en esa hoja conviven filas de tasa y filas de conteo con nombres
parecidos.
"""
import io

import openpyxl
import pytest

from shared.data.bcrd_labor import BcrdLaborUnavailable, parse_trimestral


def _libro(filas):
    wb = openpyxl.Workbook()
    hoja = wb.active
    hoja.title = "Indicadores"
    for r in filas:
        hoja.append(r)
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def _libro_encft():
    """Réplica mínima del layout real: arranca en III-2014, con nota al pie en la etiqueta."""
    return _libro([
        ["Principales Indicadores"],
        ["Condición", 2014, None, 2015, None, None, None],
        [None, "III", "IV", "I", "II", "III", "IV"],
        ["Ocupados Informales", 2100000, 2150000, 2200000, 2250000, 2300000, 2350000],
        ["SU1: Tasa de Desocupación 4/", 8.8, 7.9, 7.5, 7.1, 6.8, 6.4],
    ])


class TestElTrimestreSaleDelRomano:
    def test_el_libro_arranca_en_III_y_no_se_renumera_desde_I(self):
        """Numerar por posición etiquetaría el primer dato como 2014-Q1: dos trimestres
        corridos, y el error viaja a toda la serie."""
        s = parse_trimestral(_libro_encft(), "SU1: Tasa de Desocupación")
        assert s[0] == ("2014-Q3", 8.8)
        assert s[1] == ("2014-Q4", 7.9)

    def test_el_anio_se_propaga_desde_la_celda_combinada(self):
        s = dict(parse_trimestral(_libro_encft(), "SU1: Tasa de Desocupación"))
        assert s["2015-Q1"] == 7.5 and s["2015-Q4"] == 6.4

    def test_la_serie_viene_ordenada_y_completa(self):
        s = parse_trimestral(_libro_encft(), "SU1: Tasa de Desocupación")
        assert [p for p, _ in s] == ["2014-Q3", "2014-Q4",
                                     "2015-Q1", "2015-Q2", "2015-Q3", "2015-Q4"]


class TestLaEtiquetaSeCompararExacto:
    def test_la_marca_de_nota_al_pie_no_impide_encontrar_la_fila(self):
        """La hoja trimestral pega «4/» al final y la anual no."""
        assert parse_trimestral(_libro_encft(), "SU1: Tasa de Desocupación")

    def test_una_fila_de_CONTEOS_falla_en_vez_de_devolver_numeros(self):
        """«Ocupados Informales» son millones. Si el filtro 0-100 no estuviera, entrarían
        como si fueran una tasa. Que falle es la respuesta correcta."""
        with pytest.raises(BcrdLaborUnavailable, match="rango 0-100"):
            parse_trimestral(_libro_encft(), "Ocupados Informales")

    def test_una_etiqueta_inexistente_lo_DICE(self):
        with pytest.raises(BcrdLaborUnavailable, match="no se encontró la fila"):
            parse_trimestral(_libro_encft(), "Tasa Que No Existe")


class TestElLayoutSeBuscaPorCONTENIDO:
    def test_sin_fila_de_trimestres_falla_en_vez_de_leer_otra_cosa(self):
        libro = _libro([["Condición", 2014, 2015], ["SU1: Tasa de Desocupación", 8.8, 7.5]])
        with pytest.raises(BcrdLaborUnavailable, match="fila de trimestres"):
            parse_trimestral(libro, "SU1: Tasa de Desocupación")

    def test_una_fila_de_titulo_de_mas_no_rompe_la_lectura(self):
        """Se busca por contenido, no por índice: si el BCRD agrega un título arriba, una
        posición fija leería otra cosa en silencio."""
        filas = [["Banco Central"], ["Nota nueva del emisor"]] + [
            ["Condición", 2024, None, None, None],
            [None, "I", "II", "III", "IV"],
            ["SU1: Tasa de Desocupación 4/", 5.1, 5.0, 4.9, 4.8],
        ]
        s = parse_trimestral(_libro(filas), "SU1: Tasa de Desocupación")
        assert s[0] == ("2024-Q1", 5.1) and len(s) == 4
