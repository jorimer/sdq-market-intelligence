"""Verificación normativa — el módulo que decide si se puede acusar a alguien.

Cada test protege una frase que el informe puede publicar contra el órgano evaluado. El
orden va de la más cara a la más barata: primero las que producirían una acusación falsa.
"""
import pytest

from modules.law_intel.normativa import comprobar, comprobar_obligacion

CONSULTA = {"obligacion": "art-54", "cita_a": "ley:1-12", "tipo": "decreto",
            "desde": "2012-01-25", "hasta": "2026-12-31"}
VENCE = "2012-07-23"

_DECRETO = {"id": "do:decreto:134-14", "tipo": "decreto", "numero": "134-14",
            "fecha_promulgacion": "2014-04-09",
            "gaceta": {"numero": "10752", "fecha": "2014-04-15"}}


def _resp(resultados, concluyente, **alcance):
    return {"alcance": {"vacio_es_concluyente": concluyente, **alcance},
            "resultados": resultados}


def test_un_fallo_del_API_NUNCA_se_traduce_a_incumplimiento():
    """El error más caro que este módulo puede cometer: acusar al Estado de incumplir por
    culpa de nuestra clave o de una caída de red. El estado declarado queda intacto."""
    from shared.data.jurisai_client import JurisAICredencial

    def _rechaza(**kw):
        raise JurisAICredencial("401")

    c = comprobar_obligacion(CONSULTA, VENCE, _rechaza)
    assert c.veredicto == "no_verificable" and not c.acusa


def test_una_lista_vacia_NO_alcanza_para_acusar():
    """«No encontrado» y «no existe» son cosas distintas. Sin `vacio_es_concluyente`, el
    veredicto es `sin_registro_publico`, que no afirma nada contra nadie."""
    c = comprobar_obligacion(CONSULTA, VENCE,
                             lambda **kw: _resp([], False, huecos=["1997-2001"]))
    assert c.veredicto == "sin_registro_publico" and not c.acusa
    assert "1997-2001" in c.evidencia, "el hueco declarado tiene que viajar con el veredicto"


def test_con_el_alcance_concluyente_SI_se_puede_afirmar_que_no_se_dictó():
    """Es la única puerta al `incumplida`, y la evidencia lleva el corpus y su cobertura:
    es lo que sostiene la afirmación ante quien la discuta."""
    c = comprobar_obligacion(
        CONSULTA, VENCE,
        lambda **kw: _resp([], True, corpus="gaceta_oficial",
                           completo_desde="1997-01-01", completo_hasta="2026-07-31"))
    assert c.veredicto == "incumplida" and c.acusa
    assert "gaceta_oficial" in c.evidencia and "1997-01-01" in c.evidencia


def test_el_caso_real_del_articulo_54_da_cumplida_TARDE():
    """Plazo vencido el 2012-07-23, Decreto 134-14 del 2014-04-09: veintiún meses tarde.
    Es el incumplimiento más limpio del expediente y hasta ahora se sostenía a mano."""
    c = comprobar_obligacion(CONSULTA, VENCE, lambda **kw: _resp([_DECRETO], True))
    assert c.veredicto == "cumplida_tarde"
    assert "134-14" in c.evidencia and "2012-07-23" in c.evidencia
    assert "10752" in c.evidencia, "la Gaceta es lo que vuelve oponible a la norma"


def test_con_varias_normas_manda_la_PRIMERA_en_el_tiempo():
    """Tomar la más reciente haría parecer tardío un cumplimiento que fue en plazo."""
    en_plazo = dict(_DECRETO, id="do:decreto:11-12", numero="11-12",
                    fecha_promulgacion="2012-03-01")
    c = comprobar_obligacion(CONSULTA, VENCE,
                             lambda **kw: _resp([_DECRETO, en_plazo], True))
    assert c.veredicto == "cumplida" and "11-12" in c.evidencia


def test_solo_se_comprueban_las_obligaciones_que_DECLARAN_su_consulta():
    """Constituir una comisión o convocar una reunión no deja rastro en la Gaceta.
    Pretender verificarlas por acá produciría un `incumplida` sobre un acto que esta fuente
    no puede ver — que es exactamente la acusación que el módulo existe para impedir."""
    from modules.law_intel.obligaciones import cargar_obligaciones

    obs = cargar_obligaciones("end_2030")
    cs = comprobar(obs, lambda **kw: _resp([_DECRETO], True))
    declaran = [o.id for o in obs if o.verificacion_normativa]
    assert {c.obligacion for c in cs} == set(declaran)
    assert "art-51-comision-bicameral" not in {c.obligacion for c in cs}


def test_la_fecha_de_gaceta_FALTA_a_menudo_y_no_se_interpola_cruda():
    """El número de Gaceta y su fecha viajan por separado, y el corpus real devolvió el
    134-14 con número y sin fecha. Interpolarla sin comprobar publicó «del None» dentro de
    la evidencia que sostiene el veredicto — una frase que el informe cita tal cual."""
    sin_fecha = dict(_DECRETO, gaceta={"numero": "10753", "fecha": None})
    c = comprobar_obligacion(CONSULTA, VENCE, lambda **kw: _resp([sin_fecha], True))
    assert "10753" in c.evidencia, "el número solo ya es respaldo: no se calla por la fecha"
    assert "None" not in c.evidencia
    # Se comprueba la FRASE, no el final de la cadena: desde que toda comprobación lleva la
    # procedencia de su corpus, la evidencia sigue después. Fijar el `endswith` ataba el test
    # a dónde terminaba el texto y no a lo que el texto tiene que decir.
    assert "Gaceta 10753." in c.evidencia


class TestLaGrietaQueElEmisorAvisa:
    """Con `vence`, el API marca `veredicto_sensible_a_publicacion` cuando el dictado cae a
    ≤30 días del plazo y no consta la fecha de Gaceta: el caso al filo, donde «dentro» y
    «fuera» del plazo dependen de un dato que falta en dos tercios del corpus."""

    def _resp_sensible(self, **kw):
        base = _resp([dict(_DECRETO, fecha_promulgacion="2012-07-10")], True)
        base.update({"veredicto_sensible_a_publicacion": True, "holgura_dias": 13})
        base.update(kw)
        return base

    def test_un_veredicto_fragil_NO_se_publica_como_firme(self):
        c = comprobar_obligacion(CONSULTA, VENCE, lambda **kw: self._resp_sensible())
        assert c.veredicto == "no_verificable", (
            "«cumplida» absuelve: afirmarla sobre una diferencia no medida es el error caro")
        assert "SENSIBLE A LA PUBLICACIÓN" in c.evidencia
        assert "13 días" in c.evidencia

    def test_con_holgura_amplia_el_veredicto_sigue_siendo_firme(self):
        """Lo que vuelve sólido al art. 54 no es el método sino sus 625 días de holgura:
        ninguna fecha de publicación imaginable mueve ese veredicto."""
        r = _resp([_DECRETO], True)
        r["holgura_dias"] = -625
        r["veredicto_sensible_a_publicacion"] = False
        c = comprobar_obligacion(CONSULTA, VENCE, lambda **kw: r)
        assert c.veredicto == "cumplida_tarde"
        assert "625 días" in c.evidencia, "la holgura se publica: es lo que sostiene la firmeza"


def test_un_vacio_sobre_un_tipo_SIN_MEDIR_nunca_acusa():
    """El emisor mide su corpus por TIPO. Un `incumplida` sobre un universo que nadie midió
    es la peor salida posible de este módulo.

    La regla no cambió; cambió qué tipos están medidos. Salieron de acá `reglamento`
    (2026-08-19) y `resolucion` (2026-08-21), los dos porque el emisor cerró su barrido y lo
    demostró contra producción. Se mueven por EVIDENCIA, no porque estorben — que es la única
    razón que vale para aflojar un guard que protege de una acusación falsa."""
    for tipo in ("constitucion", "circular"):
        c = comprobar_obligacion(dict(CONSULTA, tipo=tipo), VENCE, lambda **kw: _resp([], True))
        assert c.veredicto == "sin_registro_publico", tipo


class TestLoQueElEmisorConfirmoElDiecinueve:
    def test_un_vacio_sobre_REGLAMENTO_ya_puede_acusar(self):
        """Estuvo vetado mientras la pregunta seguía abierta. El emisor la respondió con
        evidencia contra producción: `tipo=reglamento` y `tipo=decreto` devuelven alcances
        idénticos campo a campo en 2012-2026."""
        c = comprobar_obligacion(dict(CONSULTA, tipo="reglamento"), VENCE,
                                 lambda **kw: _resp([], True))
        assert c.veredicto == "incumplida"

    def test_una_RESOLUCION_ya_puede_acusar(self):
        """2026-08-21: el emisor cerró el barrido de resoluciones —4.393 de 4.397, con 13 de
        17 años completos— y su alcance ya responde `true` en los rangos completos.

        Dejarla vetada dejó de proteger y empezó a estorbar: un `incumplida` legítimo salía
        como `sin_registro_publico`. Un cinturón que veta de más no es prudente, es impreciso.
        """
        c = comprobar_obligacion(dict(CONSULTA, tipo="resolucion"), VENCE,
                                 lambda **kw: _resp([], True))
        assert c.veredicto == "incumplida"

    def test_pero_el_ALCANCE_del_emisor_sigue_mandando(self):
        """Los cuatro años con hueco (2011, 2014, 2015, 2019) los declara él: si la consulta
        los abarca devuelve `vacio_es_concluyente: false` y no se acusa. Nuestro cinturón
        acompaña esa comprobación, no la reemplaza."""
        c = comprobar_obligacion(dict(CONSULTA, tipo="resolucion"), VENCE,
                                 lambda **kw: _resp([], False))
        assert c.veredicto == "sin_registro_publico"

    def test_una_norma_DUPLICADA_se_cuenta_una_vez(self):
        """El emisor devolvió un tiempo cinco normas dos veces —mismo id, gradas distintas—
        porque el enlace entre gradas se rehace por campañas. Ya lo corrigió; deduplicamos
        igual, porque un recuento que depende de que nadie duplique es un acuerdo tácito."""
        from modules.law_intel.normativa import _sin_duplicados

        dup = [dict(_DECRETO, grada="registral"), dict(_DECRETO, grada="texto")]
        unicas = _sin_duplicados(dup)
        assert len(unicas) == 1
        assert unicas[0]["grada"] == "texto", "la leída dice estrictamente más"


class TestElSelloDelCorpus:
    def test_una_acusacion_declara_la_antiguedad_de_su_evidencia(self):
        """El corpus del emisor pasó de 596 a 9.335 decretos en semanas. Sin procedencia, un
        veredicto de hoy no es reproducible mañana y nadie puede saberlo."""
        r = _resp([], True, corpus="gaceta_oficial", medido_al="2026-08-18T03:40:48")
        c = comprobar_obligacion(CONSULTA, VENCE, lambda **kw: r)
        assert c.veredicto == "incumplida"
        assert "2026-08-18" in c.evidencia

    def test_sin_HUELLA_la_acusacion_dice_que_no_se_podra_detectar_el_cambio(self):
        """La frase cambió al corregir cuál de los dos campos detecta deriva: lo que no se
        puede hacer sin `instantanea` no es «auditar» en abstracto, es saber si el corpus
        cambió cuando este veredicto se reemita."""
        c = comprobar_obligacion(CONSULTA, VENCE, lambda **kw: _resp([], True))
        assert "no se podrá detectar si cambió" in c.evidencia


class TestCualDeLosDosCamposDetectaDERIVA:
    """El campo intuitivo es el que NO sirve, y el error ya se cometió acá.

    `medido_al` se leyó como «cuándo se comprobó por última vez». El emisor lo corrigió con
    evidencia de producción: en unas horas su corpus creció 546 normas —de 9.983 a 10.529— y
    `medido_al` no se movió ni un segundo. Es el piso de antigüedad de la evidencia, no una
    marca de frescura: los años cerrados conservan su medición original porque el pasado no
    cambia.

    Una detección de deriva montada sobre `medido_al` nunca dispararía.
    """

    def _alcance(self, **kw):
        base = {"corpus": "gaceta_oficial", "vacio_es_concluyente": True,
                "medido_al": "2026-08-18T03:40:48",
                "instantanea": {"normas_leidas": 10529, "constancias": 8739}}
        base.update(kw)
        return base

    def test_la_HUELLA_es_lo_que_detecta_deriva(self):
        from modules.law_intel.normativa import huella_del_corpus
        h = huella_del_corpus(self._alcance())
        assert h == {"normas_leidas": 10529, "constancias": 8739}

    def test_medido_al_responde_OTRA_pregunta(self):
        from modules.law_intel.normativa import antiguedad_de_la_evidencia
        assert antiguedad_de_la_evidencia(self._alcance()) == "2026-08-18T03:40:48"

    def test_una_acusacion_lleva_LOS_DOS(self):
        """Guardar uno solo deja ciega a la mitad: la huella dice si el corpus cambió; el otro
        dice cuán vieja es la evidencia más débil que sostiene la afirmación."""
        c = comprobar_obligacion(CONSULTA, VENCE,
                                 lambda **kw: {"alcance": self._alcance(), "resultados": []})
        assert c.veredicto == "incumplida"
        assert "10529" in c.evidencia and "2026-08-18" in c.evidencia

    def test_sin_huella_se_DECLARA_que_no_se_podra_detectar_el_cambio(self):
        a = self._alcance()
        a.pop("instantanea")
        c = comprobar_obligacion(CONSULTA, VENCE,
                                 lambda **kw: {"alcance": a, "resultados": []})
        assert "no se podrá detectar si cambió" in c.evidencia


class TestLaCitaDeGacetaLaCOMPONEElEmisor:
    """`texto_citable` lo entregó el emisor después de que publicáramos «Gaceta 10753 del
    None». Usarlo no es comodidad: quien conoce el formato correcto de una cita oficial es
    quien publica el corpus, y el día que cambie nos enteramos sin tocar nada."""

    def test_se_prefiere_el_texto_del_EMISOR(self):
        n = dict(_DECRETO, gaceta={"numero": "10753", "fecha": None,
                                   "texto_citable": "Gaceta Oficial 10753"})
        c = comprobar_obligacion(CONSULTA, VENCE, lambda **kw: _resp([n], True))
        assert "Publicada en Gaceta Oficial 10753." in c.evidencia
        assert "None" not in c.evidencia

    def test_sin_texto_citable_se_compone_acá_y_sigue_sin_muñón(self):
        """El respaldo propio no se borra: hay respuestas viejas y puede haber otros emisores.
        Lo que no puede volver es el «del None»."""
        n = dict(_DECRETO, gaceta={"numero": "10753", "fecha": None})
        c = comprobar_obligacion(CONSULTA, VENCE, lambda **kw: _resp([n], True))
        assert "Gaceta 10753." in c.evidencia and "None" not in c.evidencia

    def test_sin_numero_no_se_inventa_respaldo(self):
        n = dict(_DECRETO, gaceta={"numero": None, "fecha": None})
        c = comprobar_obligacion(CONSULTA, VENCE, lambda **kw: _resp([n], True))
        assert "Gaceta" not in c.evidencia



class TestLaProcedenciaAcompanaATODOVeredicto:
    """La procedencia acompañaba solo a las acusaciones, y la asimetría era defendible a
    medias: `incumplida` es lo que alguien puede refutar, así que ahí pesa más.

    Pero un `cumplida_tarde` también se publica en un informe que se vende, y también hay que
    poder explicar después por qué su cifra ya no coincide con la de hoy — que es lo que la
    doctrina exige de CUALQUIER dato publicado, no solo de los que acusan.
    """

    ALCANCE = {"corpus": "gaceta_oficial", "vacio_es_concluyente": True,
               "medido_al": "2026-08-18T03:40:48",
               "instantanea": {"normas_leidas": 10759}}

    def test_un_CUMPLIMIENTO_tambien_lleva_la_huella(self):
        c = comprobar_obligacion(CONSULTA, VENCE,
                                 lambda **kw: {"alcance": self.ALCANCE,
                                               "resultados": [_DECRETO]})
        assert c.veredicto == "cumplida_tarde"
        assert "10759" in c.evidencia, "sin la huella no se puede auditar después"

    def test_un_SIN_REGISTRO_PUBLICO_tambien(self):
        a = dict(self.ALCANCE, vacio_es_concluyente=False, huecos=["2011"])
        c = comprobar_obligacion(CONSULTA, VENCE,
                                 lambda **kw: {"alcance": a, "resultados": []})
        assert c.veredicto == "sin_registro_publico"
        assert "10759" in c.evidencia

    def test_pero_un_fallo_del_API_no_INVENTA_procedencia(self):
        """Sin alcance no hay corpus del que hablar: el emisor no llegó a responder, y
        fabricar una frase sobre su cobertura sería inventar procedencia sin consulta."""
        from shared.data.jurisai_client import JurisAIUnavailable

        def _cae(**kw):
            raise JurisAIUnavailable("timeout")

        c = comprobar_obligacion(CONSULTA, VENCE, _cae)
        assert c.veredicto == "no_verificable"
        assert "huella" not in c.evidencia and "corpus" not in c.evidencia.lower()


def test_REGLA_ninguna_comprobacion_se_arma_sin_el_constructor():
    """ESTRUCTURAL: la asimetría existió porque la procedencia se agregaba en UN `return` de
    cinco. Un constructor único la vuelve imposible de olvidar; este test lo vuelve imposible
    de eludir."""
    import ast
    import inspect
    import textwrap

    from modules.law_intel import normativa

    arbol = ast.parse(textwrap.dedent(inspect.getsource(normativa.comprobar_obligacion)))
    crudos = [n.lineno for n in ast.walk(arbol)
              if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)
              and n.func.id == "Comprobacion"]
    assert not crudos, (
        f"se arma un `Comprobacion` a mano en las líneas {crudos}: se salta la procedencia "
        f"del corpus y el veredicto queda sin poder auditarse. Usá `_comprobacion`.")


class TestLaFechaEnDisputa:
    """El emisor marca `fecha_confiable: false` cuando la fecha guardada contradice al año que
    declara el número de la norma. No la corrige, y con razón: la corrupción está en el portal
    de origen —hay fichas con `FechaPromulgacion = '01 de January de 1900'`— y reconstruirla
    exigiría inventar el día.

    El día es justo lo que decide si se dictó en plazo, así que un veredicto de plazo sobre una
    fecha en disputa es firmeza prestada. Antes de esto, `_fecha()` la leía sin mirar la
    bandera y el veredicto salía firme igual.
    """

    def _norma(self, fecha, **extra):
        return dict(_DECRETO, fecha_promulgacion=fecha, **extra)

    def test_una_fecha_en_disputa_NO_produce_veredicto_de_plazo(self):
        n = self._norma("2012-07-01", fecha_confiable=False,
                        fecha_en_disputa={"anio_segun_numero": 2012,
                                          "anio_publicacion_segun_fuente": 2012})
        c = comprobar_obligacion(CONSULTA, VENCE, lambda **kw: _resp([n], True))
        assert c.veredicto == "no_verificable"
        assert "EN DISPUTA" in c.evidencia
        assert "el día es lo que decide" in c.evidencia

    def test_las_DOS_mitades_viajan_para_que_el_lector_juzgue(self):
        """El emisor las manda a propósito: coinciden en 50 de 54 casos, así que dan
        corroboración sin que él elija por nosotros. Ocultarlas sería tirar esa corroboración."""
        n = self._norma("2012-07-01", fecha_confiable=False,
                        fecha_en_disputa={"anio_segun_numero": 2014,
                                          "anio_publicacion_segun_fuente": 2013})
        c = comprobar_obligacion(CONSULTA, VENCE, lambda **kw: _resp([n], True))
        assert "2014" in c.evidencia and "2013" in c.evidencia

    def test_si_el_AÑO_decide_solo_el_veredicto_se_sostiene(self):
        """Misma lógica que los 625 días de holgura del 134-14: lo que sostiene el veredicto no
        es el método, es que el margen se come la incertidumbre. Si la norma es de un año
        posterior al del vencimiento, ninguna fecha imaginable dentro de ese año la vuelve
        puntual — y negarse a concluir ahí sería cautela decorativa."""
        n = self._norma("2014-04-09", fecha_confiable=False,
                        fecha_en_disputa={"anio_segun_numero": 2014,
                                          "anio_publicacion_segun_fuente": 2014})
        c = comprobar_obligacion(CONSULTA, VENCE, lambda **kw: _resp([n], True))
        assert c.veredicto == "cumplida_tarde"
        assert "en disputa" in c.evidencia, "la salvedad viaja igual"

    def test_una_fecha_CONFIABLE_no_cambia_de_comportamiento(self):
        """El contrapeso: los campos son aditivos y no deben mover lo que ya funcionaba."""
        c = comprobar_obligacion(CONSULTA, VENCE,
                                 lambda **kw: _resp([self._norma("2014-04-09")], True))
        assert c.veredicto == "cumplida_tarde"
        assert "disputa" not in c.evidencia
