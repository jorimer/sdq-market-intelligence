"""El parser de los cuadros EMFA, contra las formas reales de los siete archivos.

Cada caso de abajo salió de un defecto MEDIDO contra los archivos publicados, no de
imaginar qué podría salir mal. Los cuatro juntos multiplicaron por 2,6 lo que el conector
extraía (17.997 → 47.304 observaciones) y sacaron una fecha futura del resultado.
"""
import datetime as dt

from shared.data.secmca_client import (
    TASA_MAXIMA_CREIBLE_PCT, SECMCAClient, clasificar_hoja, discover_country_files,
    normalizar_escala, parse_cuadro, parse_periodo, parse_valor, titulo_de_hoja,
)


class TestDescubrimientoDeArchivos:
    def test_encuentra_los_cuadros_por_pais(self):
        html = ('<a href="/wp-content/uploads/2026/08/RD_CMCA_EMFA_2_DIV.xls">RD</a>'
                '<a href="/wp-content/uploads/2025/09/NC_CMCA_EMFA_2_DIV.xls">NI</a>')
        assert discover_country_files(html) == {
            "DOM": "https://www.secmca.org/wp-content/uploads/2026/08/RD_CMCA_EMFA_2_DIV.xls",
            "NIC": "https://www.secmca.org/wp-content/uploads/2025/09/NC_CMCA_EMFA_2_DIV.xls",
        }

    def test_la_url_no_se_puede_fijar_en_el_codigo(self):
        """La ruta lleva el año y mes de subida, así que cambia en cada actualización."""
        antes = discover_country_files(
            '<a href="/wp-content/uploads/2025/09/RD_CMCA_EMFA_2_DIV.xls">x</a>')
        despues = discover_country_files(
            '<a href="/wp-content/uploads/2026/08/RD_CMCA_EMFA_2_DIV.xls">x</a>')
        assert antes["DOM"] != despues["DOM"]


class TestClasificacionDeHojas:
    def test_la_tasa_no_se_confunde_con_el_credito(self):
        """«TASAS ... SOBRE PRÉSTAMOS» también dice «PRÉSTAMOS»: el orden importa."""
        assert clasificar_hoja(
            "TASAS DE INTERÉS BANCARIAS SOBRE PRÉSTAMOS EN MONEDA NACIONAL") == "tasa_activa_mn"
        assert clasificar_hoja(
            "PRESTAMOS DE LAS OTRAS SOCIEDADES DE DEPÓSITO AL SECTOR PRIVADO POR DESTINO "
            "ECONÓMICO EN MONEDA NACIONAL") == "credito_osd_privado_mn"

    def test_tolera_la_marca_de_nota_al_pie_pegada(self):
        """Panamá escribe «EN MN1/» y Guatemala «BANCARIAS1/ SOBRE»: perdíamos sus cuadros."""
        assert clasificar_hoja(
            "PRESTAMOS DE LAS OTRAS SOCIEDADES DE DEPÓSITO AL SECTOR PRIVADO POR DESTINO "
            "ECONÓMICO EN MN1/") == "credito_osd_privado_mn"
        assert clasificar_hoja(
            "TASAS DE INTERÉS BANCARIAS1/ SOBRE PRÉSTAMOS EN MONEDA NACIONAL"
        ) == "tasa_activa_mn"

    def test_descarta_los_cuadros_en_moneda_extranjera(self):
        assert clasificar_hoja(
            "TASAS DE INTERÉS BANCARIAS SOBRE PRÉSTAMOS EN MONEDA EXTRANJERA") is None

    def test_el_titulo_sale_del_cuerpo_de_la_hoja(self):
        """Nunca del nombre de la hoja ni del Índice: en RD 15 de sus 19 enlaces apuntan
        a hojas inexistentes, con los nombres de la convención de Costa Rica."""
        filas = [[""], [""], ["TASAS DE INTERÉS BANCARIAS PASIVAS EN MONEDA NACIONAL1/"]]
        assert clasificar_hoja(titulo_de_hoja(filas)) == "tasa_pasiva_mn"


class TestPeriodos:
    def test_las_tres_formas_que_conviven_en_un_archivo(self):
        assert parse_periodo(2001.0, "Dic") == dt.date(2001, 12, 31)     # RD
        assert parse_periodo("01", "Dic-01") == dt.date(2001, 12, 31)    # El Salvador
        assert parse_periodo("", dt.date(2016, 1, 31)) == dt.date(2016, 1, 31)  # Costa Rica

    def test_una_nota_al_pie_no_es_una_observacion(self):
        """Con el año arrastrado, un mes escondido en una nota fabricaba un corte a
        diciembre de 2026 — tres meses en el FUTURO — en el cuadro de tasas de RD."""
        assert parse_periodo("", "     Suministro de electricidad y agua",
                             anio_arrastrado=2026) is None

    def test_el_anio_se_arrastra_cuando_la_celda_esta_vacia(self):
        """Se escribe una vez y los once meses siguientes lo dejan en blanco: sin arrastre
        se reconocía una fila de cada doce (Guatemala daba 26 de ~300)."""
        assert parse_periodo("", "Ene", anio_arrastrado=2002) == dt.date(2002, 1, 31)
        assert parse_periodo("", "Ene") is None      # sin año no se inventa nada


class TestValores:
    def test_lo_que_la_fuente_escribe_donde_no_hay_dato(self):
        """`n.a` / `n.d.` van a None. En una tasa, cero es una afirmación fuerte y falsa."""
        for ausente in ("n.a", "n.d.", "-", "...", ""):
            assert parse_valor(ausente) is None
        assert parse_valor(5.4) == 5.4
        assert parse_valor("3,09") == 3.09


class TestCuadroCompleto:
    def _cuadro(self):
        return [
            ["", "", "", ""],
            ["", "", "Consumo", "Consumo"],
            ["", "", "Tarjeta de Crédito", "Otros"],
            ["", "", "(1)", "(2)"],
            [2001.0, "Dic", 12.5, "n.a"],
            ["", "Ene", 12.7, 8.1],
            ["", "Feb", None, 8.2],
            ["", "1/ Incluye Microempresa", "", ""],
        ]

    def test_arma_las_etiquetas_juntando_los_niveles_del_encabezado(self):
        etiquetas = {e for _, e, _ in parse_cuadro(self._cuadro())}
        assert etiquetas == {"Consumo · Tarjeta de Crédito", "Consumo · Otros"}

    def test_arrastra_el_anio_y_corta_en_las_notas(self):
        obs = parse_cuadro(self._cuadro())
        cortes = sorted({c for c, _, _ in obs})
        assert cortes == [dt.date(2001, 12, 31), dt.date(2002, 1, 31), dt.date(2002, 2, 28)]

    def test_el_ausente_persiste_como_ausente(self):
        obs = parse_cuadro(self._cuadro())
        dic = {e: v for c, e, v in obs if c == dt.date(2001, 12, 31)}
        assert dic["Consumo · Otros"] is None          # era "n.a"
        assert dic["Consumo · Tarjeta de Crédito"] == 12.5


class TestContrato:
    def test_el_fixture_declara_la_ausencia_de_la_tasa_activa_salvadorena(self):
        """El Salvador no publica tasa activa. Es una ausencia de la FUENTE, y el conector
        la deja ver en vez de rellenarla."""
        recs = SECMCAClient().fetch()
        cuadros = {r.dimension: {x.series.split("::")[0] for x in recs if x.dimension == r.dimension}
                   for r in recs}
        assert "tasa_activa_mn" not in cuadros["SLV"]
        assert "tasa_activa_mn" in cuadros["DOM"]

    def test_solo_las_tasas_se_declaran_comparables_entre_paises(self):
        """El crédito va en moneda local y el cuadro deja la unidad en blanco
        («Saldos en millones de ___»): armonizar la metodología no armoniza la unidad."""
        assert SECMCAClient.COMPARABLE_ENTRE_PAISES == {"tasa_activa_mn", "tasa_pasiva_mn"}
        recs = SECMCAClient().fetch()
        credito = next(r for r in recs if r.series.startswith("credito_"))
        assert credito.unit == "moneda local, unidad no declarada"
        assert next(r for r in recs if r.series.startswith("tasa_")).unit == "%"


class TestEscalaDeLasTasas:
    """EMFA armoniza la metodología, NO la escala — y eso llegó al primer boletín real.

    El PDF decía «República Dominicana registra 0.186% en julio de 2026» sobre una tasa de
    consumo que es del 18,6%. La cifra era REAL: lo que cambió fue su forma. Y el error no
    era parejo: RD y Nicaragua publican como fracción, mientras Guatemala, Honduras, Costa
    Rica, Panamá y El Salvador ya publican en porcentaje, así que una comparación cruda
    ponía un 0,58 al lado de un 54,5 como si midieran lo mismo.
    """

    def test_la_fraccion_se_lleva_a_porcentaje(self):
        obs = [(dt.date(2026, 7, 31), "Tarjeta", 0.580246),
               (dt.date(2026, 7, 31), "Consumo", 0.186)]
        salida, avisos = normalizar_escala(obs)
        assert [v for _, _, v in salida] == [58.0246, 18.6]
        assert not avisos

    def test_lo_que_ya_viene_en_porcentaje_no_se_toca(self):
        obs = [(dt.date(2026, 7, 31), "Consumo", 54.5135),
               (dt.date(2026, 7, 31), "Ahorro", 5.72)]
        salida, _ = normalizar_escala(obs)
        assert [v for _, _, v in salida] == [54.5135, 5.72]

    def test_la_escala_se_decide_por_AÑO_porque_cambia_dentro_de_la_serie(self):
        """La tasa pasiva dominicana está en porcentaje hasta 2003 y en fracción desde 2004.

        Un criterio único para toda la serie dejaría cien veces mal a uno de los dos tramos.
        """
        obs = [(dt.date(2003, 12, 31), "Plazo", 24.42),      # ya en %
               (dt.date(2004, 12, 31), "Plazo", 0.2457)]     # fracción
        salida, _ = normalizar_escala(obs)
        assert [v for _, _, v in salida] == [24.42, 24.57]

    def test_una_tasa_implausible_se_descarta_y_queda_constancia(self):
        """Fail-closed: publicar una tasa de tres dígitos porque la normalización falló es
        peor que no publicarla."""
        obs = [(dt.date(2026, 7, 31), "Rara", TASA_MAXIMA_CREIBLE_PCT + 1)]
        salida, avisos = normalizar_escala(obs)
        assert salida[0][2] is None
        assert avisos and "fuera de rango" in avisos[0]

    def test_las_ausencias_sobreviven_a_la_normalizacion(self):
        salida, _ = normalizar_escala([(dt.date(2026, 7, 31), "X", None)])
        assert salida == [(dt.date(2026, 7, 31), "X", None)]

    def test_el_fixture_trae_tasas_en_rango_creible(self):
        """Contra el dato real: ninguna plaza publica una tasa de tres dígitos."""
        recs = SECMCAClient().fetch()
        tasas = [r.value for r in recs if r.series.startswith("tasa_") and r.value is not None]
        assert tasas
        assert max(tasas) <= TASA_MAXIMA_CREIBLE_PCT
        # Y ninguna quedó en escala de fracción: una tasa activa de un panel entero no puede
        # tener su máximo por debajo del 1,5%.
        assert max(tasas) > 1.5


def test_el_lector_APLICA_la_normalizacion_de_escala():
    """Que la función exista no alcanza: hay que comprobar que el lector la llama.

    El fixture se guarda ya normalizado, así que un conector que dejara de normalizar
    seguiría pasando todos los tests de arriba — pasó al escribirlos. Lo que falla en ese
    caso es el dato NUEVO, contra los archivos reales, donde nadie lo estaría mirando.
    """
    import ast
    import inspect

    from shared.data import secmca_client

    fuente = inspect.getsource(secmca_client.cuadros_del_libro)
    arbol = ast.parse(fuente.lstrip())
    llama = any(isinstance(n, ast.Call) and isinstance(n.func, ast.Name)
                and n.func.id == "normalizar_escala" for n in ast.walk(arbol))
    assert llama, (
        "`cuadros_del_libro` no llama a `normalizar_escala`: las tasas saldrían con la "
        "escala cruda de cada país —fracción en RD y Nicaragua, porcentaje en el resto— y "
        "el boletín volvería a imprimir «0.186%» sobre una tasa del 18,6%.")
