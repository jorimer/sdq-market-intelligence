"""SISDOM «Indicadores Área Especial END» — indicador 2.40 y los que vengan detrás.

Las filas de acá son REALES: se capturaron el 2026-08-24 de las ediciones 2024 (MEPyD) y
2025 (Hacienda), con el espacio delante del nombre de hoja, con la columna 2016 REPETIDA y
con los tipos mezclados que el emisor usa en el mismo encabezado.
"""
import pytest

from shared.data.sisdom_end import (ANIO_DE_SOLAPAMIENTO, Observacion, SisdomError, anio_de,
                                    fila_del_total, fila_de_encabezado, instrumento_de,
                                    leer_hoja, nombre_de_hoja, salto_en_el_solapamiento,
                                    serie_de)

#: El encabezado real de la hoja « END 2.40» de SISDOM 2024. Tres cosas juntas: el primer año
#: es TEXTO («2000») y el resto números («2001.0»), y 2016 aparece DOS veces — una por cada
#: encuesta.
ENCABEZADO = ["Desagregaciones", "2000", 2001.0, 2009.0, 2010.0, 2015.0, 2016.0,
              "2016*", "2020*", "2025*"]
TOTAL_PAIS = ["Total país", 0.8633461990651202, 0.8587207106947947, 0.8832121676617328,
              0.9571030680401318, 0.9047, 0.9162977369648456, 0.9072428800748205,
              0.9524202663087717, 0.8836262986822886]
ZONA_URBANA = ["Zona Urbana", 0.80, 0.79, 0.81, 0.9197823054255978, 0.83, 0.84, 0.85,
               0.86, 0.87]

HOJA = [["SISTEMA DE INDICADORES SOCIALES"], [], ["Área Especial 1"], ["Eje 2"],
        ["2000 - 2024"], ["Índice", "END 2.40  Brecha de ingreso"], [],
        ENCABEZADO, TOTAL_PAIS, ["Zona de residencia"], ZONA_URBANA]

#: Otras hojas del mismo libro rotulan el total como «Total Nacional». Son dos tercios.
HOJA_CON_OTRO_ROTULO = [["x"], [], [], [], [], [], [],
                        ["Desagregaciones", 2010.0, "2020*"],
                        ["Total Nacional", 0.5, 0.6]]


class TestComoSeLlamaLaHoja:
    def test_tolera_el_espacio_ADELANTE_del_nombre(self):
        """La hoja del 2.40 se llama `« END 2.40»`. Buscar por igualdad exacta la pierde, y
        perderla se lee como que el indicador no tiene fuente — que es el estado en el que
        estuvo hasta hoy."""
        hojas = ["Índice", "END 2.39a", " END 2.40", "END 2.41a"]
        assert nombre_de_hoja(hojas, "2.40") == " END 2.40"

    def test_no_confunde_2_4_con_2_40(self):
        assert nombre_de_hoja(["END 2.4a", " END 2.40"], "2.4") is None
        assert nombre_de_hoja(["END 2.4", " END 2.40"], "2.4") == "END 2.4"

    def test_sin_hoja_devuelve_None(self):
        assert nombre_de_hoja(["Índice", "END 2.1a"], "2.40") is None


class TestElInstrumentoVIAJA:
    def test_el_asterisco_es_la_ENCUESTA_NUEVA(self):
        """Lo declara la Nota 5 del propio libro: el asterisco es la ENCFT."""
        assert instrumento_de("2016*") == "ENCFT"
        assert instrumento_de(2016.0) == "ENFT"

    def test_2016_aparece_DOS_veces_y_se_conservan_las_DOS(self):
        """Es un solapamiento, no un empalme: las dos encuestas midieron el mismo año y dan
        valores distintos. Elegir una acá sería elegirla para todos los llamadores."""
        obs = leer_hoja(HOJA)
        de_2016 = [o for o in obs if o.anio == ANIO_DE_SOLAPAMIENTO]
        assert len(de_2016) == 2
        assert {o.instrumento for o in de_2016} == {"ENFT", "ENCFT"}

    def test_el_salto_del_solapamiento_se_puede_DECLARAR(self):
        """No se empalma —el emisor no publica factor y fabricarlo sería inventar una
        convención— pero sí hay que poder decir de qué tamaño es el escalón."""
        viejo, nuevo = salto_en_el_solapamiento(leer_hoja(HOJA))
        assert viejo == pytest.approx(0.91630, abs=1e-4)
        assert nuevo == pytest.approx(0.90724, abs=1e-4)
        assert abs(nuevo - viejo) / viejo * 100 == pytest.approx(0.99, abs=0.1)

    def test_sin_solapamiento_devuelve_None(self):
        assert salto_en_el_solapamiento(leer_hoja(HOJA_CON_OTRO_ROTULO)) is None

    def test_la_serie_de_UN_instrumento_es_lo_unico_comparable(self):
        obs = leer_hoja(HOJA)
        enft = serie_de(obs, "ENFT")
        encft = serie_de(obs, "ENCFT")
        assert 2016 in enft and 2016 in encft and enft[2016] != encft[2016]
        assert 2010 in enft and 2010 not in encft


class TestQueFilaEsElPAIS:
    def test_acepta_los_DOS_rotulos_vivos_del_libro(self):
        """«Total país» en unas hojas y «Total Nacional» en otras. Quedarse con uno deja
        fuera dos tercios de las hojas devolviendo vacío, que se lee como «no hay dato»."""
        assert fila_del_total([f[0] if f else None for f in HOJA]) == 8
        assert leer_hoja(HOJA_CON_OTRO_ROTULO)[0].valor == 0.5

    def test_NO_sirve_una_desagregacion_como_si_fuera_el_pais(self):
        obs = leer_hoja(HOJA)
        assert obs[0].valor != ZONA_URBANA[1]

    def test_sin_total_nacional_LEVANTA(self):
        sin_total = [["x"], [], [], [], [], [], [], ENCABEZADO, ZONA_URBANA]
        with pytest.raises(SisdomError, match="ninguna fila nacional"):
            leer_hoja(sin_total)

    def test_sin_fila_de_encabezado_LEVANTA(self):
        with pytest.raises(SisdomError, match="DESAGREGACI"):
            leer_hoja([["x"], ["Total país", 1.0]])


class TestLosTiposMezcladosDelEncabezado:
    def test_texto_numero_y_asterisco_en_la_misma_fila(self):
        assert anio_de("2000") == 2000
        assert anio_de(2001.0) == 2001
        assert anio_de("2016*") == 2016
        assert anio_de("Desagregaciones") is None

    def test_un_booleano_no_es_un_valor(self):
        """`isinstance(True, int)` es verdadero en Python y colaría un 1,0 como observación."""
        hoja = [["x"], [], [], [], [], [], [], ["Desagregaciones", 2010.0],
                ["Total país", True]]
        with pytest.raises(SisdomError, match="ninguna fila nacional"):
            leer_hoja(hoja)


def test_CONTRA_LA_LEY_la_base_de_2010_se_reproduce():
    """El 2.40 de la ley: base 0,95 en 2010. La hoja da 0,9571 — Δ 0,75%, dentro de la
    tolerancia del oráculo. Verificado abriendo la celda el 2026-08-24, no tomado de un
    informe: es la comprobación que la auditoría dejó explícitamente pendiente.
    """
    base = serie_de(leer_hoja(HOJA), "ENFT")[2010]
    assert abs(base - 0.95) / 0.95 * 100 < 2.0


def test_la_edicion_viaja_con_la_observacion():
    """Dos ediciones publican esta serie y hay que poder rastrear una discrepancia."""
    obs = leer_hoja(HOJA, edicion=2024)
    assert all(o.edicion == 2024 for o in obs)
    assert Observacion(anio=2025, valor=0.88, instrumento="ENCFT", edicion=2025).edicion == 2025
