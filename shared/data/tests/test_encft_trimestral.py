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


# ── Las CUATRO medidas de subutilización ─────────────────────────────────────────────

class TestLasCuatroMedidasDeSubutilizacion:
    """El BCRD publica SU1 a SU4 en la misma fila del mismo trimestre y se ingería SU1.

    Al primer trimestre de 2026: SU1 = 4,95% y SU4 = 10,55%. Citar la angosta subestima la
    holgura laboral a MENOS DE LA MITAD, y la diferencia es exactamente la población que le
    importa al crédito de consumo — el subocupado por horas tiene empleo e ingreso
    INSUFICIENTE, no aparece en la desocupación y sí aparece en la mora.

    No hubo que escribir un parser: `parse_trimestral` ya sabía leer cualquier fila por su
    etiqueta. Faltaba pedírselas. Es el patrón de esta base de datos —la fuente publica más
    de lo que persistimos, y ya la estábamos descargando entera— visto por quinta vez.
    """

    ETIQUETAS = (
        "SU1: Tasa de Desocupación",
        "SU2: Desocupación y Subocupación",
        "SU3: Desocupación y Fuerza de Trabajo Potencial",
        "SU4: Desocupación + Subocupación + Fuerza de Trabajo Potencial",
    )

    def test_el_ensamblado_pide_las_cuatro_y_no_solo_la_angosta(self):
        import inspect
        from shared.data import bcrd_labor
        src = inspect.getsource(bcrd_labor.fetch_bcrd_labor_market)
        for clave in ("underutilization_su2_trimestral", "underutilization_su3_trimestral",
                      "underutilization_su4_trimestral"):
            assert clave in src, f"«{clave}» no se pide: la holgura sale a la mitad"

    def test_las_cuatro_se_PERSISTEN(self):
        from modules.social_dev.social_sync import _MERCADO_LABORAL_TRIMESTRAL
        for clave in ("unemployment_rate_trimestral", "underutilization_su2_trimestral",
                      "underutilization_su3_trimestral", "underutilization_su4_trimestral"):
            assert clave in _MERCADO_LABORAL_TRIMESTRAL

    def test_cada_serie_lleva_SU_medida_en_la_etiqueta(self):
        """«subutilización» a secas no dice cuál de las cuatro es, y las cuatro conviven en
        el mismo informe."""
        from modules.social_dev.social_sync import _MERCADO_LABORAL_TRIMESTRAL
        for clave, (etiqueta, _u) in _MERCADO_LABORAL_TRIMESTRAL.items():
            if "underutilization" in clave:
                assert clave.split("_")[1].upper() in etiqueta.upper(), (
                    f"«{etiqueta}» no dice qué medida es")

    def test_el_informe_sirve_la_ANCHA_y_la_angosta_con_su_brecha(self):
        from modules.banking_score.reports.capacidad_de_pago import _TEMAS_LABORALES
        assert _TEMAS_LABORALES["unemployment_rate_trimestral"] == "desocupacion_abierta_su1_pct"
        assert _TEMAS_LABORALES["underutilization_su4_trimestral"] == (
            "subutilizacion_amplia_su4_pct")

    def test_la_plantilla_pide_la_AMPLIA_si_se_cita_una_sola(self):
        from shared.narrative.claude_engine import THIN_TEMPLATES
        thin = THIN_TEMPLATES["banking_sector_map"]
        assert "citá la AMPLIA" in thin
        assert "holgura_que_SU1_no_ve_pp" in thin


class TestLaPrecisionDeCadaEstimacion:
    """La ENCFT es una encuesta y su precisión venía publicada al lado, sin usar.

    Dos hojas del mismo libro —1.434 filas— con error estándar, intervalo al 95% y
    coeficiente de variación de cada estimación trimestral. Servíamos las cifras desnudas.
    """

    RAW = None

    def _raw(self):
        import pathlib
        p = pathlib.Path("/Users/ricardomercado/Downloads/00_Indicadores.xlsx")
        return p.read_bytes() if p.exists() else None

    def test_el_puente_entre_los_DOS_vocabularios_esta_declarado(self):
        """La hoja de indicadores dice «SU1: Tasa de Desocupación» y la de precisión «Tasa
        de desocupación (SU1)». Emparejarlos por parecido pegaría la precisión de una serie
        a los valores de otra, y el resultado se vería perfectamente normal."""
        from shared.data.bcrd_labor import PRECISION_POR_ETIQUETA
        assert PRECISION_POR_ETIQUETA["SU1: Tasa de Desocupación"] == \
            "Tasa de desocupación (SU1)"
        assert len(PRECISION_POR_ETIQUETA) >= 9

    def test_el_ano_se_lee_venga_como_numero_o_como_TEXTO(self):
        """La misma columna de la misma hoja mezcla los dos tipos: 195 celdas de texto y una
        numérica. Leer solo el numérico dejaba `anio` sin propagar durante bloques enteros y
        la serie salía VACÍA sin error — el parser «funcionaba»."""
        from shared.data.bcrd_labor import _anio
        assert _anio(2014) == 2014
        assert _anio("2014") == 2014
        assert _anio(" 2015 ") == 2015
        assert _anio("Año") is None
        assert _anio(1999) is None and _anio("3000") is None
        assert _anio(None) is None and _anio(True) is None

    def test_las_series_que_se_CITAN_llevan_su_precision(self):
        from shared.data.bcrd_labor import _PRECISION_DE_LAS_SERVIDAS
        for clave in ("unemployment_rate_trimestral", "underutilization_su4_trimestral",
                      "informality_rate_trimestral"):
            assert clave in _PRECISION_DE_LAS_SERVIDAS

    def test_la_precision_se_PERSISTE_como_temas_propios(self):
        """El CV y los extremos del intervalo son magnitudes distintas del valor: meterlos
        en `disaggregation` los volvería texto y nadie podría compararlos."""
        import inspect
        from modules.social_dev import social_sync
        src = inspect.getsource(social_sync._sync_bcrd_mercado_laboral)
        for sufijo in ("_cv", "_ic95_inf", "_ic95_sup"):
            assert sufijo in src


class TestLaAperturaRegional:
    """Siete indicadores × cinco dominios × once años, en una hoja que ya descargábamos.

    De `Regiones` solo se computaba UNA brecha anual —máximo menos mínimo de SU2— para un
    indicador de la END. Las tasas por dominio no se persistían, y la holgura laboral no es
    nacional: en 2025 la subutilización amplia va de 6,5% en el Cibao a 14,0% en el Sur, más
    del doble. Un informe que cite solo el número del país describe un promedio que no le
    ocurre a ningún territorio.
    """

    def test_los_dominios_se_leen_del_ENCABEZADO_y_no_se_declaran(self):
        """Si el BCRD agrega o renombra un dominio, entra solo. Una lista fija dejaría de
        verlo en silencio, que es como se pierde una serie sin que nada falle."""
        import inspect
        from shared.data import bcrd_labor
        src = inspect.getsource(bcrd_labor.parse_regiones)
        assert "dominios = [" in src and "fila[1:]" in src
        # Lo que SÍ se declara es qué indicadores se persisten: eso es decisión nuestra.
        assert len(bcrd_labor.REGIONALES_A_PERSISTIR) == 7

    def test_las_cuatro_medidas_de_holgura_estan_entre_los_persistidos(self):
        from shared.data.bcrd_labor import REGIONALES_A_PERSISTIR
        for su in ("SU1", "SU2", "SU3", "SU4"):
            assert any(su in e for e in REGIONALES_A_PERSISTIR), f"falta {su} por región"

    def test_la_clave_lleva_la_CADENCIA(self):
        """La apertura regional es ANUAL y la nacional es trimestral. Sin la cadencia en la
        clave, alguien promedia un año contra un trimestre — que es el mismo cuidado que ya
        se tuvo al separar la ENCFT anual de la trimestral."""
        from shared.data.bcrd_labor import REGIONALES_A_PERSISTIR
        for clave in REGIONALES_A_PERSISTIR.values():
            assert clave.endswith("_regional_anual"), clave

    def test_el_dominio_va_en_entity_key_y_no_en_el_tema(self):
        """Así una serie es (indicador, dominio, año) y se comparan dominios sin parsear
        texto. En el tema, cada dominio sería una serie distinta y no habría con qué
        ordenarlos."""
        import inspect
        from modules.social_dev import social_sync
        src = inspect.getsource(social_sync._sync_bcrd_mercado_laboral)
        assert "entity=_slug_dominio(dominio)" in src

    def test_dos_dominios_no_colapsan_en_la_misma_clave(self):
        from modules.social_dev.social_sync import _slug_dominio
        dominios = ("Total País", "Región Ozama o Metropolitana", "Región Norte o Cibao",
                    "Región Sur", "Región Este")
        claves = [_slug_dominio(d) for d in dominios]
        assert len(claves) == len(set(claves)), f"colisión: {claves}"
        assert _slug_dominio("Total País") == "nacional"
