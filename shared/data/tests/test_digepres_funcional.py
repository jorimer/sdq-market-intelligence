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

from shared.data.digepres_funcional import (BANDA_PCT_PIB, DOCUMENTOS,
                                            SIN_CUADRO_FUNCIONAL, DigepresError, devengado_de,
                                            fila_salud, leer_cuadro, leer_pct_pib_del_emisor,
                                            lineas_de, numeros_de, razon_contra_pib, rotulo_de,
                                            unidad_de, verificar, x_de_columna, xs_de_columna)


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

#: 2019, libro de presupuesto ejecutado: inicial · modificaciones · vigente · comprometido ·
#: devengado · pagado · balance · % de ejecución. El caso que rompe la lectura por
#: porcentaje: 75.929.264.764 sobre el vigente da 96,017% y 75.942.579.256 da 96,034%, y el
#: emisor imprime 96,0 para los dos.
FILA_2019_FUNCIONAL = [(18, "4.2"), (52, "Salud"), (244, "75,929,264,764.0"),
                       (322, "3,149,841,984.8"), (397, "79,079,106,748.8"),
                       (467, "76,329,605,728.4"), (541, "75,942,579,256.3"),
                       (611, "75,942,579,256.3"), (691, "3,136,527,492.5"), (756, "96.0")]

#: La MISMA obra, tabla por objeto del gasto: los objetos suman el total, y ese total coincide
#: al peso con el devengado de arriba. Es el cruce que resuelve la ambigüedad del cuadro
#: funcional sin tener que elegir una columna a ojo.
FILA_2019_OBJETO = [(26, "4.2"), (45, "Salud"), (151, "1,772,852,831.5"),
                    (222, "1,782,335,769.4"), (363, "7,984,762,039.9"),
                    (434, "7,729,640,902.5"), (504, "5,180,562,507.5"),
                    (571, "50,743,317,311.7"), (651, "749,107,893.7"),
                    (714, "75,942,579,256.3")]

#: 2012, clasificador viejo: la función Salud es «223» y no «4.2». Sirve para dos cosas: que
#: el código de la fila no se cuente como cifra, y que el rótulo salga igual con otro código.
FILA_2012_OBJETO = [(23, "223"), (51, "SALUD"), (174, "6,597,008,056.1"),
                    (324, "4,657,368,232.5"), (399, "2,016,145,806.8"),
                    (470, "19,445,987,439.0"), (550, "9,957,623,272.6"),
                    (635, "78,000,000.0"), (692, "42,752,132,806.9")]


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


class TestLaColumnaSeEligePorLasIDENTIDADES:
    """No por posición y no por encabezado: por las cuentas que el propio cuadro publica."""

    def test_el_cuadro_funcional_por_su_porcentaje_de_ejecucion(self):
        monto, layout = devengado_de(numeros_de([(x, t) for x, t in FILA_2009]))
        assert (monto, layout) == (23534.9, "funcional")

    def test_la_tabla_por_objeto_por_la_suma_de_sus_objetos(self):
        monto, layout = devengado_de(numeros_de([(x, t) for x, t in FILA_2019_OBJETO]))
        assert (monto, layout) == (75942579256.3, "por_objeto")

    def test_el_total_por_objeto_ES_el_devengado_funcional(self):
        """La misma obra trae las dos tablas y las dos tienen que dar la misma cifra. Es el
        cruce más fuerte que hay acá: son dos aperturas distintas del mismo gasto."""
        objeto, _ = devengado_de(numeros_de([(x, t) for x, t in FILA_2019_OBJETO]))
        assert objeto == 75942579256.3

    def test_el_codigo_del_clasificador_NO_es_una_cifra(self):
        """«4.2» y «223» valen menos que el umbral de monto y entraban como porcentaje. Eso
        rompía la rama por objeto, que exige que la fila NO traiga porcentajes, y el año
        entero se perdía diciendo que ninguna identidad cerraba."""
        assert 4.2 not in numeros_de([(x, t) for x, t in FILA_2019_OBJETO])
        assert 223.0 not in numeros_de([(x, t) for x, t in FILA_2012_OBJETO])

    def test_el_clasificador_VIEJO_da_el_mismo_rotulo(self):
        assert rotulo_de([(x, t) for x, t in FILA_2012_OBJETO]) == "SALUD"
        monto, layout = devengado_de(numeros_de([(x, t) for x, t in FILA_2012_OBJETO]))
        assert (monto, layout) == (42752132806.9, "por_objeto")

    def test_una_fila_AMBIGUA_levanta_en_vez_de_elegir(self):
        """En 2019 el presupuesto inicial y el devengado redondean al mismo 96,0% contra el
        vigente, porque las modificaciones del año fueron chicas. Ahí el cuadro funcional
        solo no alcanza — y la salida correcta es decirlo, no quedarse con uno."""
        with pytest.raises(DigepresError, match="ambigua"):
            devengado_de(numeros_de([(x, t) for x, t in FILA_2019_FUNCIONAL]))

    def test_sin_montos_suficientes_levanta(self):
        with pytest.raises(DigepresError, match="identidad"):
            devengado_de([4.2, 97.0])


class TestLaColumnaDelPIB:
    def test_el_informe_trae_DOS_columnas_de_PIB(self):
        """La de la izquierda es el año ANTERIOR, que el informe arrastra para comparar."""
        filas = [_p(CABECERA_2015, top=60)]
        assert len(xs_de_columna(filas, "PIB")) == 2

    def test_se_toma_la_ULTIMA_que_es_la_del_ano_del_informe(self):
        """El defecto que esto cierra: la versión anterior devolvía la primera y publicaba la
        razón del año anterior. En 2015 las dos daban 1,9 y no se veía; el cruce contra el
        libro de 2014 lo destapó, porque su devengado es el número de la columna izquierda."""
        filas = [_p(CABECERA_2015, top=60)]
        # 482 y no 477: el encabezado derecho viaja partido en «%» y «PIB», y el que nombra
        # la columna es el segundo. El dato de la fila cae a cinco puntos de ahí.
        assert x_de_columna(filas, "PIB") == 482.0


class TestLaRazonSeCOMPUTA:
    def test_se_computa_aunque_el_emisor_publique_la_suya(self):
        """Preferir la del emisor donde existe cose la serie con DOS denominadores: el suyo
        es de su añada y el nuestro de la serie rebasada a 2018. El salto entre 2011 y 2015
        sería de quién hizo la división, no gasto público."""
        d = leer_cuadro(_p(FILA_2009), 2009, pib_nominal=1.7347e12, unidad="millones")
        assert d.procedencia_de_la_razon == "computado"
        assert d.pct_pib == pytest.approx(1.357, abs=0.002)
        assert d.monto == 23534.9

    def test_la_del_emisor_viaja_igual_como_contraste(self):
        d = leer_cuadro(_p(FILA_2015, top=100) + _p(CABECERA_2015, top=60), 2015,
                        pib_nominal=3.1967e12, unidad="millones")
        assert d.pct_pib_del_emisor == 1.9
        assert d.procedencia_de_la_razon == "computado"

    def test_sin_PIB_nominal_se_usa_la_del_emisor_y_se_declara(self):
        d = leer_cuadro(_p(FILA_2015, top=100) + _p(CABECERA_2015, top=60), 2015)
        assert (d.pct_pib, d.procedencia_de_la_razon) == (1.9, "emisor")

    def test_sin_pct_pib_y_sin_PIB_nominal_LEVANTA(self):
        """Servir el monto suelto sería servir otra magnitud."""
        with pytest.raises(DigepresError, match="PIB nominal"):
            leer_cuadro(_p(FILA_2009), 2009, pib_nominal=None, unidad="millones")

    def test_una_pagina_sin_fila_de_salud_LEVANTA_con_el_motivo(self):
        with pytest.raises(DigepresError, match="Salud"):
            leer_cuadro(_p([(100, "Educacion"), (200, "1.0"), (300, "2.0")]), 2009,
                        pib_nominal=1e12)


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


class TestElRegistroDeDocumentos:
    """Que anio sale de que documento es una DECISION, no un hallazgo de expresion regular."""

    def test_ningun_anio_esta_declarado_dos_veces(self):
        """Un anio no puede estar a la vez servido y sin cuadro: la contradiccion se lee como
        que hay dato cuando no lo hay, que es el peor de los dos errores."""
        assert not (set(DOCUMENTOS) & set(SIN_CUADRO_FUNCIONAL))

    def test_la_serie_no_tiene_huecos_CALLADOS(self):
        """Todo anio entre el primero y el ultimo, o tiene documento o tiene motivo escrito.
        Un hueco que no esta en ninguna de las dos listas desaparece sin aviso."""
        cubiertos = set(DOCUMENTOS) | set(SIN_CUADRO_FUNCIONAL)
        faltan = sorted(set(range(min(DOCUMENTOS), max(cubiertos) + 1)) - cubiertos)
        assert not faltan, f"anios sin documento y sin motivo declarado: {faltan}"

    def test_cada_hueco_dice_POR_QUE(self):
        for anio, motivo in SIN_CUADRO_FUNCIONAL.items():
            assert len(motivo) > 40, f"{anio}: «{motivo}» no explica nada"

    def test_cubre_la_linea_base_de_la_ley(self):
        """La ley fija 1,4% para 2009. Sin ese anio no hay contra que verificar nada."""
        assert 2009 in DOCUMENTOS

    def test_las_metas_de_2020_y_2025_estan_declaradas_como_hueco(self):
        """No se pueden medir, y eso es un hecho del emisor que el expediente tiene que
        poder citar — no una ausencia que el lector descubra sumando."""
        assert 2020 in SIN_CUADRO_FUNCIONAL and 2025 in SIN_CUADRO_FUNCIONAL
