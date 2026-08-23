"""El cuadro funcional de DIGEPRES — indicador 2.33 de la END.

Las filas de acá son REALES: se capturaron de los informes del emisor con sus coordenadas,
con sus guiones blandos y con los números partidos tal como los devuelve el extractor. Un
fixture inventado no habría reproducido ninguno de los tres defectos que rompieron las
primeras versiones de este lector.

El modo de falla que persiguen no es que el lector se rompa. Es que devuelva una serie
plausible mil veces corrida, porque el mismo cuadro va en millones en 2009 y en unidades de
peso en 2010.
"""
import pytest

from shared.data.digepres_funcional import (BANDA_PCT_PIB, DigepresError, fila_salud,
                                            leer_cuadro, leer_pct_pib_del_emisor, lineas_de,
                                            razon_contra_pib, rotulo_de, unidad_de, verificar)


def _p(fila, top=100.0):
    """Palabras con coordenadas, como las devuelve el extractor de PDF."""
    return [{"text": t, "x0": float(x), "top": float(top)} for x, t in fila]


#: 2009, cuadro clásico: rótulo limpio, tres columnas, millones de RD$.
FILA_2009 = [(146, "Salud"), (353, "24,090.1"), (426, "23,534.9"), (494, "97.7")]

#: 2015, cuadro numerado. Trae las tres trampas juntas: el código «4.2» que ABRE la fila y es
#: un número, el guion BLANDO pegado a otro guion, y el paréntesis suelto de un negativo.
FILA_2015 = [(76, "4.2"), (87, "-\xad‐"), (91, "Salud"), (209, "51,781.2"), (246, "1.9%"),
             (278, "5"), (281, "8,908.5"), (320, "("), (322, "1,110.8)"), (360, "57,797.8"),
             (401, "56,052.8"), (441, "97.0%"), (477, "1.9%")]
CABECERA_2015 = [(209, "Devengado"), (246, "%PIB"), (360, "Modificado"), (401, "Devengado"),
                 (477, "%"), (482, "PIB")]


class TestElRotulo:
    def test_ignora_el_codigo_de_funcion_que_ABRE_la_fila(self):
        """«4.2» es un número y encabeza la fila: cortar «en el primer número» dejaba el
        rótulo vacío, que fue el segundo intento fallido de este lector."""
        assert rotulo_de([(x, t) for x, t in FILA_2015]) == "SALUD"

    def test_ignora_el_guion_BLANDO(self):
        """El extractor devuelve `-\\xad‐` en los informes de 2015 y 2016. Sin limpiarlo, la
        fila sencillamente no aparece — y una fila que no aparece se lee como año sin dato."""
        assert "\xad" in FILA_2015[1][1]
        assert rotulo_de([(x, t) for x, t in FILA_2015]) == "SALUD"

    def test_ignora_el_PARENTESIS_suelto_de_un_negativo(self):
        """«( 1,110.8)» viaja como dos palabras y la primera no tiene dígitos: colarla
        convertía el rótulo en «SALUD (», que no coincide con nada."""
        assert any(t == "(" for _, t in FILA_2015)
        assert rotulo_de([(x, t) for x, t in FILA_2015]) == "SALUD"

    def test_el_rotulo_clasico_tambien_sale_limpio(self):
        assert rotulo_de([(x, t) for x, t in FILA_2009]) == "SALUD"


class TestQueFilaEsLaCorrecta:
    def test_encuentra_la_fila_de_salud(self):
        assert fila_salud([_p(FILA_2009)]) is not None

    def test_NO_confunde_la_funcion_con_la_INSTITUCION(self):
        """«Salud Pública y Asistencia Social» es un ministerio y aparece en el cuadro
        institucional del MISMO informe, con una cifra bastante mayor. Confundirlas no rompe
        nada: publica otro universo contra la meta de la ley."""
        institucional = [(60, "207"), (90, "SEC."), (110, "DE"), (125, "ESTADO"),
                         (150, "DE"), (165, "SALUD"), (200, "PUBLICA"), (350, "30,675.1")]
        assert fila_salud([_p(institucional)]) is None

    def test_sin_fila_de_salud_devuelve_None_y_no_la_de_al_lado(self):
        otra = [(146, "Educacion"), (353, "37,880.7"), (426, "36,816.1"), (494, "97.2")]
        assert fila_salud([_p(otra)]) is None


class TestLaUnidadNoSeADIVINA:
    def test_lee_la_unidad_que_el_cuadro_declara(self):
        assert unidad_de("( En Millones de RD$)") == "millones"
        assert unidad_de("(Valores en RD$)") == "unidades"

    def test_sin_declaracion_devuelve_None(self):
        """Entre millones y unidades hay un factor de mil. Elegir la que da una cifra
        plausible sería ajustar el método a la respuesta."""
        assert unidad_de("Cuadro 9 - Clasificacion Funcional 2010") is None

    def test_el_factor_de_cada_unidad(self):
        assert razon_contra_pib(100.0, "millones", 1e10) == pytest.approx(1.0)
        assert razon_contra_pib(100e6, "unidades", 1e10) == pytest.approx(1.0)

    def test_una_unidad_desconocida_LEVANTA(self):
        with pytest.raises(DigepresError, match="unidad"):
            razon_contra_pib(1.0, "miles", 1e10)


class TestLosDosCinturones:
    def test_la_banda_ataja_el_error_de_UNIDAD(self):
        """El caso real: el informe de 2010 leído como millones da 1.684.437% del PIB. El
        guard lo para; sin él, la serie saldría plausible y mil veces corrida."""
        with pytest.raises(DigepresError, match="fuera de la banda"):
            verificar(1_684_437.0, None)

    def test_la_banda_tambien_ataja_por_abajo(self):
        with pytest.raises(DigepresError, match="fuera de la banda"):
            verificar(BANDA_PCT_PIB[0] / 2, None)

    def test_una_razon_creible_pasa(self):
        verificar(1.9, None)

    def test_si_discrepamos_del_EMISOR_levanta(self):
        """El cinturón más fuerte, y solo existe cuando el emisor publica su propia razón: si
        la nuestra y la suya difieren, algo se leyó mal y da igual cuál esté bien."""
        with pytest.raises(DigepresError, match="difieren"):
            verificar(1.9, 3.8)

    def test_el_redondeo_del_emisor_no_dispara_el_guard(self):
        """Publica con un decimal: sobre 1,9% un punto de redondeo ya son ~5%."""
        verificar(1.94, 1.9)


class TestLaRazonPreferidaEsLaDelEMISOR:
    def test_cuando_el_cuadro_la_publica_se_usa_la_suya(self):
        """El indicador ES una razón contra el PIB. Tomarla publicada evita elegir una columna
        de dinero entre diez y evita dividir por un PIB de otra fuente y otra añada."""
        d = leer_cuadro(_p(FILA_2015, top=100) + _p(CABECERA_2015, top=60), 2015)
        assert d.pct_pib == 1.9
        assert d.procedencia_de_la_razon == "emisor"

    def test_sin_pct_pib_publicado_se_computa_y_se_declara(self):
        d = leer_cuadro(_p(FILA_2009), 2009, pib_nominal=1.7347e12, unidad="millones")
        assert d.procedencia_de_la_razon == "computado"
        assert d.pct_pib == pytest.approx(1.357, abs=0.002)
        assert d.unidad_del_monto == "millones"

    def test_sin_pct_pib_y_sin_PIB_nominal_LEVANTA(self):
        """Servir el monto suelto sería servir otra magnitud."""
        with pytest.raises(DigepresError, match="PIB nominal"):
            leer_cuadro(_p(FILA_2009), 2009, pib_nominal=None, unidad="millones")

    def test_una_pagina_sin_fila_de_salud_LEVANTA_con_el_motivo(self):
        with pytest.raises(DigepresError, match="Salud"):
            leer_cuadro(_p([(100, "Educacion"), (200, "1.0"), (300, "2.0")]), 2009,
                        pib_nominal=1e12)

    def test_la_lectura_por_defecto_es_lo_EJECUTADO(self):
        """La ley dice «gasto», y gasto es lo que se gastó. Que el presupuesto vigente
        reproduzca mejor la línea base (Δ 0,8% contra 3,1%) se declara en el expediente y NO
        cambia el defecto: elegir la columna que mejor cuadra, después de ver las dos, sería
        ajustar el método a la respuesta."""
        d = leer_cuadro(_p(FILA_2009), 2009, pib_nominal=1.7347e12, unidad="millones")
        assert d.monto == 23534.9


def test_las_lineas_se_agrupan_por_su_coordenada_vertical():
    """Los guiones blandos y los superíndices caen unas décimas por encima de la línea;
    separarlos partiría la fila en dos y la fila partida no coincide con nada."""
    palabras = _p([(10, "Salud")], top=100.0) + _p([(50, "1,0")], top=100.7)
    assert len(lineas_de(palabras)) == 1


def test_el_pct_pib_lejano_al_encabezado_no_se_toma():
    """Un porcentaje a media página del encabezado no es el de esa columna: es el de
    ejecución, que ronda el 97% y no se parece en nada a una razón contra el PIB."""
    lejos = [(76, "Salud"), (100, "97.0%")]
    cab = [(600, "%"), (605, "PIB")]
    assert leer_pct_pib_del_emisor([_p(cab, top=60), _p(lejos, top=100)]) is None
