"""El catálogo de trámites de gob.do, y la cifra que mide.

Las prosas de acá son REALES: se capturaron de la API el 2026-08-25, con su HTML, sus
`&nbsp;` y sus espacios múltiples. Una prosa inventada no habría reproducido el defecto que
tumbó la primera versión del extractor.
"""
import pytest

from shared.data.gobdo_tramites import (ANCLAS, ANCLAS_DEBILES, ANCLAS_FUERTES,
                                        BANDA_DIAS, CAMPOS_CON_PROSA,
                                        PREFIJO_OBLIGATORIO, Tiempo, TramitesError,
                                        leer_listado, limpiar_prosa, resumen, tiempo_declarado,
                                        tramite_de)

#: Los tres únicos trámites del catálogo que declaran su tiempo, con la frase real.
CNZFE = ("<p>​</p><p>Si el pago se realiza, el costo será Regular.</p><p><strong>Información "
         "Adicional</strong></p><p style=\"text-align:justify\"><strong>REGULAR:</strong>&nbsp;"
         "el tiempo de entrega es de 5 días      laborables.</p>")
SNS = "<p>El tiempo de entrega es de 3 días laborables luego de depositados los documentos.</p>"
MICM = "<p>Apertura de empresas: el tiempo de respuesta es de 48 horas laborables.</p>"

#: Prosas que traen una cifra de tiempo que NO es el plazo del trámite. Son las que hicieron
#: que la primera versión —sin ancla— devolviera 23% en vez de 0,4%.
MULTA = ("<p>La concesión podrá suspenderse por seis meses, con un monto de CIEN MIL PESOS "
         "(RD$100,000.00) de multa.</p>")
CONDICION = ("<p>Si cuando realiza el pago quedan 5 días laborables o menos de la reunión del "
             "Consejo Directivo, debe esperar la siguiente.</p>")
VIGENCIA = "<p>La certificación emitida tiene una vigencia de tres (3) meses.</p>"


class TestLaGramaticaEstaANCLADA:
    """Una cifra de tiempo sin ancla no es el tiempo del trámite."""

    @pytest.mark.parametrize("prosa,esperado", [
        (CNZFE, "5 días laborables"),
        (SNS, "3 días laborables"),
        (MICM, "48 horas laborables"),
    ])
    def test_extrae_los_tres_positivos_REALES(self, prosa, esperado):
        t = tiempo_declarado(limpiar_prosa(prosa))
        assert t is not None and t.texto_original.startswith(esperado.split()[0])
        assert t.laborables is True

    @pytest.mark.parametrize("prosa", [MULTA, CONDICION, VIGENCIA])
    def test_NO_extrae_multas_condiciones_ni_vigencias(self, prosa):
        """El defecto que publicaría un 23% que mide otra cosa."""
        assert tiempo_declarado(limpiar_prosa(prosa)) is None

    def test_el_ancla_encuentra_el_positivo_conocido(self):
        """El guard sobre el INSTRUMENTO. La versión anclada devolvió 0 en una muestra de 60
        y ese cero era cierto — pero un barrido que no encuentra nada y un barrido roto se
        ven igual. Antes de creerle a un cero se comprueba contra un positivo conocido."""
        assert tiempo_declarado(limpiar_prosa(CNZFE)) is not None

    def test_las_anclas_son_una_lista_CERRADA(self):
        """Ampliarla es una decisión que se toma acá y se mide, no algo que se hace al pasar."""
        assert len(ANCLAS) >= 5
        assert all(isinstance(a, str) and a for a in ANCLAS)


class TestLaProsaVieneSUCIA:
    def test_colapsa_los_espacios_multiples_del_emisor(self):
        """«5 días      laborables» — sin colapsar, el patrón se parte a la mitad."""
        limpia = limpiar_prosa(CNZFE)
        assert "5 días laborables" in limpia
        assert "  " not in limpia

    def test_resuelve_las_entidades_html(self):
        assert "&nbsp;" not in limpiar_prosa(CNZFE)

    def test_tolera_campos_vacios_o_nulos(self):
        assert limpiar_prosa(None, "", "<p>hola</p>") == "hola"


class TestLaCIFRAyLaUNIDAD:
    def test_prefiere_la_cifra_del_PARENTESIS_sobre_la_palabra(self):
        t = tiempo_declarado(limpiar_prosa(
            "<p>El tiempo de entrega es de tres (3) días laborables.</p>"))
        assert t is not None and t.valor == 3.0

    def test_lee_el_numero_ESCRITO_cuando_no_hay_cifra(self):
        t = tiempo_declarado(limpiar_prosa(
            "<p>El tiempo de respuesta es de quince días hábiles.</p>"))
        assert t is not None and t.valor == 15.0

    def test_las_horas_LABORABLES_se_normalizan_sobre_la_jornada(self):
        """«48 horas laborables» son 6 días de trabajo, no 2 de calendario: tratarlas como 2
        subestimaría el trámite tres veces."""
        t = tiempo_declarado(limpiar_prosa(MICM))
        assert t is not None and t.dias == 6.0

    def test_las_horas_de_CALENDARIO_se_normalizan_sobre_24(self):
        t = Tiempo(valor=48, unidad="hora", laborables=False, texto_original="48 horas")
        assert t.dias == 2.0

    @pytest.mark.parametrize("prosa,dias", [
        ("<p>El tiempo de entrega es de 2 semanas.</p>", 14.0),
        ("<p>El tiempo de respuesta es de dos meses.</p>", 60.0),
    ])
    def test_normaliza_semanas_y_meses(self, prosa, dias):
        assert tiempo_declarado(limpiar_prosa(prosa)).dias == dias

    def test_un_plazo_fuera_de_BANDA_se_descarta(self):
        """Más de un año no es un plazo de respuesta: es una vigencia o una prescripción."""
        assert tiempo_declarado(limpiar_prosa(
            "<p>El tiempo de entrega es de 30 meses.</p>")) is None
        assert BANDA_DIAS[1] == 365.0


class TestLaAUSENCIAesLaMEDICION:
    def _tramite(self, prosa=None):
        fila = {"slug": "x", "service_name": "Un trámite", "institution_name": "Instituto",
                "institution_acronym": "INS", "area_service": {"name": "Salud"},
                "is_web_mode": 1, "is_phone_mode": 0, "is_person_mode": 1,
                "price": [{"id": 1}], "visited": 10, "updated_at": "2026-08-25T00:00:00Z"}
        return tramite_de(fila, {"info_process": prosa} if prosa is not None else {})

    def test_sin_tiempo_declarado_el_campo_es_None_y_NO_cero(self):
        """Confundir «no lo declara» con «tarda cero» invertiría el hallazgo entero."""
        t = self._tramite("<p>Sin plazo alguno.</p>")
        assert t.tiempo is None

    def test_sin_DETALLE_no_se_puede_afirmar_que_no_lo_declara(self):
        """El listado no trae la prosa: ahí `None` significa «no se preguntó»."""
        fila = {"slug": "x", "service_name": "N", "institution_acronym": "INS",
                "area_service": {}, "visited": 0}
        assert tramite_de(fila, None).tiempo is None

    def test_el_resumen_publica_las_DOS_caras_y_su_denominador(self):
        ts = [self._tramite(CNZFE)] + [self._tramite("<p>nada</p>") for _ in range(9)]
        r = resumen(ts)
        assert r["declaran_su_tiempo_de_respuesta"] == 1
        assert r["no_declaran_su_tiempo_de_respuesta"] == 9
        assert r["pct_declaran_sobre_los_del_catalogo"] == 10.0
        assert r["pct_no_declaran_sobre_los_del_catalogo"] == 90.0

    def test_toda_clave_de_porcentaje_nombra_su_denominador(self):
        r = resumen([self._tramite(CNZFE)])
        for clave in (k for k in r if k.startswith("pct_")):
            assert "_sobre_" in clave

    def test_el_resumen_cita_la_OBLIGACION_que_vuelve_publicable_la_ausencia(self):
        r = resumen([self._tramite(CNZFE)])
        assert "142-2024" in r["obligacion"] and "167-21" in r["obligacion"]
        assert "no significa que el trámite sea inmediato" in r["nota"].lower()


class TestLaFormaDeLaAPI:
    def test_un_listado_sin_data_LEVANTA_en_vez_de_servir_vacio(self):
        with pytest.raises(TramitesError, match="no trae `data`"):
            leer_listado({"meta": {"total": 710}})

    def test_el_prefijo_api_queda_declarado(self):
        """Sin `/api` la ruta responde 404 con «no ha iniciado sesion», que parece un
        problema de permisos y es un problema de ruta."""
        assert PREFIJO_OBLIGATORIO == "/api"

    def test_se_leen_los_TRES_campos_de_prosa(self):
        """Ninguna institución usa el mismo; leer uno solo pierde a las otras dos."""
        assert set(CAMPOS_CON_PROSA) == {"info_process", "info_requirement", "description"}

    def test_el_tramite_recoge_los_canales_declarados(self):
        fila = {"slug": "x", "service_name": "N", "institution_acronym": "INS",
                "area_service": {"name": "A"}, "is_web_mode": 1, "is_phone_mode": 0,
                "is_person_mode": 1, "visited": 3}
        t = tramite_de(fila, {})
        assert set(t.canales) == {"en_linea", "presencial"}



class TestLasProsasQueSePerdian:
    """La primera versión detectaba 3 de 22 sobre los 710 trámites del catálogo.

    Lo que faltaba no era rigor: era cómo escribe la gente. Estas cinco prosas son REALES,
    capturadas del portal el 2026-08-25, y cada una tumbaba el extractor por un motivo
    distinto. Publicar 3 habría sido publicar una cifra siete veces menor que la real.
    """

    @pytest.mark.parametrize("institucion,prosa,esperado", [
        ("DGP",
         "<p>Se le entrega en 3 horas si es solicitado antes del mediodía.</p>",
         "3 horas"),                                    # el «le» rompía `se entrega en`
        ("PGR",
         "<p>Este proceso tiene una duración de cinco días laborables.</p>",
         "cinco días laborables"),                      # no había ancla para «duración»
        ("IDAC",
         "<p>Este proceso de preaprobación toma 1 día hábil.</p>",
         "1 día hábil"),                                # no había ancla para «toma N días»
        ("INDOTEL",
         "<p>Dentro de un plazo de quince (15) días calendario contados a partir.</p>",
         "quince (15) días calendario"),                # ni para «dentro de un plazo de»
        ("MICM",
         "<p>procesada con tiempo estimado de 48 horas laborables, debe cumplir.</p>",
         "48 horas laborables"),
    ])
    def test_detecta_las_cinco_formas_reales(self, institucion, prosa, esperado):
        t = tiempo_declarado(limpiar_prosa(prosa))
        assert t is not None, f"{institucion}: no detecta «{esperado}»"
        assert t.texto_original == esperado

    def test_el_calificador_admite_SINGULAR_y_plural(self):
        """`h[áa]biles?` exigía una «e»: casaba «hábiles» y no «hábil». Un trámite de un
        solo día es justo el que más importa y era el que se perdía."""
        for prosa, esperado in [
            ("<p>El tiempo de respuesta es de 1 día hábil.</p>", "1 día hábil"),
            ("<p>El tiempo de respuesta es de 5 días hábiles.</p>", "5 días hábiles"),
            ("<p>El tiempo de respuesta es de 30 días naturales.</p>", "30 días naturales"),
        ]:
            assert tiempo_declarado(limpiar_prosa(prosa)).texto_original == esperado

    def test_el_texto_capturado_termina_en_palabra_ENTERA(self):
        """Se publica en una tabla: «1 día h» o «3 horas si es solicitad» son jirones."""
        t = tiempo_declarado(limpiar_prosa(
            "<p>Se le entrega en 3 horas si es solicitado antes del mediodía.</p>"))
        assert t.texto_original == "3 horas"
        assert not t.texto_original.endswith((" h", " s", " cont", "solicitad"))


class TestElNivelDelAnclaVIAJA:
    """Nombrar el campo y suplirlo en prosa no son lo mismo para el informe."""

    def test_gana_la_que_NOMBRA_el_campo_aunque_aparezca_despues(self):
        """La ficha del CNZFE menciona antes una condición de agenda con la misma cifra. Con
        una lista plana ganaba el orden del texto, no el que nombra el campo."""
        t = tiempo_declarado(limpiar_prosa(
            "<p>Si cuando realiza el pago quedan 5 días laborables o menos de la reunión "
            "del Consejo. REGULAR: el tiempo de entrega es de 5 días laborables.</p>"))
        assert t.como_lo_dice == "explicito"

    def test_una_perifrasis_se_marca_como_tal(self):
        t = tiempo_declarado(limpiar_prosa(
            "<p>Este proceso tiene una duración de cinco días laborables.</p>"))
        assert t.como_lo_dice == "perifrasis"

    def test_los_dos_niveles_son_DISJUNTOS(self):
        assert not set(ANCLAS_FUERTES) & set(ANCLAS_DEBILES)
        assert set(ANCLAS) == set(ANCLAS_FUERTES) | set(ANCLAS_DEBILES)

    def test_el_resumen_separa_los_dos_niveles(self):
        from shared.data.gobdo_tramites import Tiempo, Tramite, resumen
        def _t(nivel):
            return Tramite(slug="x", nombre="N", institucion="I", institucion_sigla="I",
                           area="A", canales=(), costo_declarado=False, visitas=0,
                           actualizado=None,
                           tiempo=Tiempo(5, "dia", True, "5 días", como_lo_dice=nivel))
        r = resumen([_t("explicito"), _t("perifrasis"), _t("perifrasis")])
        assert r["lo_nombran_explicitamente"] == 1
        assert r["lo_dicen_en_perifrasis"] == 2
