"""El producto engancha al pipeline sin romper ninguna de sus reglas.

El test que más importa es el de la HUELLA. En los demás sectores el dato vive en la base, así
que un arreglo mueve el payload y la caché —que no tiene TTL— regenera. Acá el dato de la ley
vive en archivos del repositorio: sin la huella, corregir una meta del CSV dejaría a los
informes ya generados sirviendo el texto viejo indefinidamente. Ya pasó en esta plataforma con
un arreglo de contexto que se desplegó y no invalidó nada.
"""
import pytest

from modules.law_intel.ai_context import law_ai_context, secciones_sin_dato
from modules.law_intel.products import (AI_CONTEXT_FILES, SECTOR_KEY, LawProduct,
                                        expediente_fingerprint, law_manifest)
from shared.products import ProductTier
from shared.products.registry import CATALOG_BY_KEY, get_product, is_implemented

E = "end_2030"


class TestLaHuellaDelExpediente:
    def test_cambiar_el_registro_cambia_la_huella(self, tmp_path, monkeypatch):
        """Sin esto, arreglar una cifra del CSV no invalida ningún informe ya generado."""
        base = tmp_path / "falso"
        base.mkdir()
        (base / "indicadores.csv").write_text("id,eje\n1.1,1\n", encoding="utf-8")
        monkeypatch.setattr("modules.law_intel.products.RAIZ", tmp_path)
        antes = expediente_fingerprint("falso")
        (base / "indicadores.csv").write_text("id,eje\n1.1,2\n", encoding="utf-8")
        assert expediente_fingerprint("falso") != antes

    def test_agregar_un_archivo_tambien_la_cambia(self, tmp_path, monkeypatch):
        """Un `obligaciones.yaml` nuevo cambia lo que el informe afirma."""
        base = tmp_path / "falso"
        base.mkdir()
        (base / "a.csv").write_text("x", encoding="utf-8")
        monkeypatch.setattr("modules.law_intel.products.RAIZ", tmp_path)
        antes = expediente_fingerprint("falso")
        (base / "obligaciones.yaml").write_text("y", encoding="utf-8")
        assert expediente_fingerprint("falso") != antes

    def test_la_huella_viaja_en_el_payload(self):
        """Fuera del payload, la caché no la ve: es el único lugar donde sirve."""
        s = LawProduct().snapshot(ProductTier.deep_dive, "2025", E)
        assert s.payload["expediente_fingerprint"] == expediente_fingerprint(E)

    def test_expedientes_distintos_tienen_huellas_distintas(self):
        assert expediente_fingerprint(E) != expediente_fingerprint("meta_rd_2036")


class TestContratoDeProducto:
    def test_esta_en_el_catalogo_y_registrado(self):
        assert SECTOR_KEY in CATALOG_BY_KEY
        assert is_implemented(SECTOR_KEY)
        assert get_product(SECTOR_KEY) is not None

    def test_el_selector_lista_los_instrumentos(self):
        vals = {o["value"] for o in LawProduct().scope_options()}
        assert {"end_2030", "meta_rd_2036"} <= vals

    def test_un_expediente_inexistente_es_error_en_español(self):
        with pytest.raises(ValueError, match="No existe el expediente"):
            LawProduct().snapshot(ProductTier.insight, "2025", "ley-inventada")

    def test_el_pulse_no_nombra_la_entidad(self):
        """Granularidad `system`: el sensor de anonimización del ensamblador lo verifica."""
        assert LawProduct().snapshot(ProductTier.pulse, "2025", E).entity_name is None
        assert LawProduct().snapshot(ProductTier.insight, "2025", E).entity_name

    def test_los_tres_niveles_declaran_secciones(self):
        for tier in (ProductTier.pulse, ProductTier.insight, ProductTier.deep_dive):
            assert law_manifest().require_level(tier).sections


class TestElEspinazoEsElFinDeLaLey:
    """El informe se organiza por lo que la ley se propuso, no por su inventario.

    La escalera anterior se diferenciaba por CUÁNTAS secciones traía cada nivel, y su
    vocabulario —cumplimiento, verificabilidad, brechas— era el índice de una auditoría del
    instrumento. Le sirve a quien quiere enmendar la ley y a nadie más. Los tres niveles
    recorren ahora las mismas preguntas a distinta profundidad.
    """

    #: Las tres preguntas del lector. Un nivel nombrado que pierda una deja de contestar.
    ESPINAZO = ("logrado", "no_logrado", "pendiente")

    def test_los_niveles_NOMBRADOS_recorren_las_tres_preguntas(self):
        for tier in (ProductTier.insight, ProductTier.deep_dive):
            secciones = law_manifest().require_level(tier).sections
            faltan = [s for s in self.ESPINAZO if s not in secciones]
            assert not faltan, f"{tier.value} no contesta {faltan}"

    def test_el_pulse_trae_el_marcador_y_NADA_de_grano_fino(self):
        """Es la vista abierta: dice si la ley llega a donde dijo, sin abrir indicadores."""
        secciones = law_manifest().require_level(ProductTier.pulse).sections
        assert secciones == ("estado_de_la_ley",)

    def test_la_escalera_AGREGA_secciones_hacia_arriba(self):
        pulse, insight, deep = (set(law_manifest().require_level(t).sections)
                                for t in (ProductTier.pulse, ProductTier.insight,
                                          ProductTier.deep_dive))
        assert pulse < insight < deep

    def test_lo_que_distingue_al_DEEP_es_la_trayectoria_y_la_exigencia(self):
        """El Deep no se compra por más resumen: se compra por «¿va a llegar?» y «¿qué se
        puede exigir?»."""
        insight = set(law_manifest().require_level(ProductTier.insight).sections)
        deep = set(law_manifest().require_level(ProductTier.deep_dive).sections)
        assert {"coherencia_proceso", "verificabilidad", "recomendaciones"} <= deep - insight

    def test_la_PROFUNDIDAD_del_deep_no_cae_sobre_el_marcador(self):
        """Con el default («la primera analítica») la profundidad habría caído en el resumen
        que el Insight ya trae, y el nivel de arriba no aportaría nada nuevo."""
        from shared.products import section_mode
        from modules.law_intel.products import _SECCION_PROFUNDA
        secciones = law_manifest().require_level(ProductTier.deep_dive).sections
        modos = {s: section_mode(ProductTier.deep_dive, s, secciones,
                                 deep_section=_SECCION_PROFUNDA) for s in secciones}
        assert modos[_SECCION_PROFUNDA] == "deep"
        assert modos["estado_de_la_ley"] != "deep"

    def test_el_generador_PASA_la_seccion_profunda_y_no_se_queda_en_el_default(self):
        """El test de arriba comprueba la constante; éste comprueba que se USA. Sin esto, el
        día que alguien borre el argumento la profundidad vuelve al marcador en silencio y
        los dos niveles de arriba se vuelven el mismo producto."""
        import ast
        import inspect

        from modules.law_intel import products as mod
        arbol = ast.parse(inspect.getsource(mod))
        llamadas = [n for n in ast.walk(arbol)
                    if isinstance(n, ast.Call) and getattr(n.func, "id", "") == "section_mode"]
        assert llamadas, "el producto ya no pide el modo de narrativa por sección"
        for c in llamadas:
            assert any(k.arg == "deep_section" for k in c.keywords), (
                "section_mode() sin `deep_section`: la profundidad del Deep Dive caería "
                "sobre la primera sección, que es el marcador")

    def test_toda_seccion_declarada_tiene_TITULO_y_MUESTRA(self):
        """Una sección sin título sale rotulada con su clave interna; una sin muestra rompe
        la descarga de conversión, que es la que se entrega antes de cobrar."""
        from modules.law_intel.products import _SAMPLE_NARRATIVES, _SECTION_TITLES
        for tier in (ProductTier.pulse, ProductTier.insight, ProductTier.deep_dive):
            for sec in law_manifest().require_level(tier).sections:
                assert sec in _SECTION_TITLES, f"«{sec}» saldría con su clave como título"
                assert sec in _SAMPLE_NARRATIVES, f"«{sec}» rompe la muestra de {tier.value}"

    def test_la_muestra_de_cada_nivel_se_arma_entera(self):
        for tier in (ProductTier.pulse, ProductTier.insight, ProductTier.deep_dive):
            muestra = LawProduct().sample_narratives(tier)
            assert set(muestra) == set(law_manifest().require_level(tier).sections)
            assert all(t.strip() for t in muestra.values())

    def test_LOGRADO_no_se_declara_vacia_por_no_haber_logros(self):
        """«Ninguna meta se alcanzó» es una respuesta, no una brecha. Declararla sin dato la
        reemplazaría por «el informe no puede pronunciarse», que dice lo contrario."""
        ctx = law_ai_context(E, "2025")
        ctx["veredictos_por_indicador_computados"] = {"cumplen": 0, "evaluados": 12}
        assert "logrado" not in secciones_sin_dato(ctx)


class TestHonestidadDelProducto:
    """Estos tests afirman el INVARIANTE, no el estado del día.

    La primera versión decía `approved is False` y `coverage == 0.0` — cierto cuando no había
    ningún binding verificado, y falso en cuanto se promovió el primero. Un test que codifica
    la foto de hoy se rompe cuando el producto AVANZA, que es justo cuando uno no quiere
    ruido: la tentación es actualizar el número y seguir, y ahí se pierde la regla.
    """

    def test_aprobado_si_y_solo_si_mide_algo(self):
        """Declararse validado con cobertura cero sería lo que el módulo denuncia; declararse
        no-validado midiendo cuatro indicadores sería igual de falso."""
        from modules.law_intel.bindings import cobertura
        v = LawProduct().validation_state()
        mide = cobertura("end_2030")["medidos"] > 0
        assert v.approved is mide
        assert (v.score > 0) is mide
        assert "verificacion" in v.notes

    def test_la_seccion_sin_insumo_se_declara_vacia(self):
        """Un Deep Dive relleno es peor que uno más corto. Se prueba con la sección que HOY
        no tiene insumo, sea cual sea — no con una fija."""
        ctx = law_ai_context(E, "2025")
        faltan = secciones_sin_dato(ctx)
        sin_contradicciones = not ctx["contradicciones_proceso_vs_resultado_computadas"]
        assert ("coherencia_proceso" in faltan) is sin_contradicciones

    def test_la_cobertura_reportada_coincide_con_la_del_expediente(self):
        from modules.law_intel.bindings import cobertura
        assert LawProduct().data_signals().coverage == pytest.approx(
            cobertura("end_2030")["pct"] / 100.0)


class TestContextoDeIA:
    def test_las_relaciones_llegan_resueltas(self):
        """El modelo copia veredictos; no deriva ninguno de una meta y un dato."""
        ctx = law_ai_context(E, "2025")
        assert ctx["veredictos_por_indicador_computados"]["por_veredicto"]
        assert all("lectura_ya_redactada" in c
                   for c in ctx["contradicciones_proceso_vs_resultado_computadas"])
        assert all("texto" in r for r in ctx["recomendaciones_ya_redactadas"])

    def test_prohibe_el_eufemismo_del_informe_oficial(self):
        v = law_ai_context(E, "2025")["vocabulario_obligatorio"]
        assert "avance moderado" in v["no_alcanzara"]

    def test_prohibe_afirmar_incumplimiento_sin_verificar(self):
        assert "sin_registro_publico" in law_ai_context(E, "2025")["regla_de_afirmacion"]

    def test_los_dos_denominadores_van_explicitos(self):
        d = law_ai_context(E, "2025")["denominadores_del_registro"]
        assert d["indicadores_numerados_de_la_ley"] == 90
        assert d["filas_medibles_con_subfilas"] == 135

    def test_el_cierre_del_informe_llega_al_modelo(self):
        """Si la brecha y la recomendación no están en el contexto, la sección sale de memoria."""
        ctx = law_ai_context(E, "2025")
        assert ctx["brechas_de_medicion"]["con_brecha"] > 0
        assert ctx["recomendaciones_ya_redactadas"]
        assert "nunca la política" in ctx["alcance_de_la_recomendacion"]


def test_declara_sus_fuentes_de_contexto():
    """`AI_CONTEXT_FILES` es lo que mete estos archivos en la regla del sujeto y en la huella
    de la caché de narrativas. Sin declararlo, la mitad del contexto queda fuera de las dos."""
    assert "ai_context.py" in AI_CONTEXT_FILES
    assert any("accionabilidad" in f for f in AI_CONTEXT_FILES)


class TestSeñalesPorIndicador:
    """Sin ellas, el readiness resume 90 indicadores en «faltan dimensiones con dato real ()»
    —con el paréntesis vacío— y el agente de descubrimiento recibe un prompt que no nombra
    ni un indicador."""

    def test_una_señal_por_indicador_numerado(self):
        from modules.law_intel.registro import cargar
        vs = LawProduct().variable_signals()["signals"]
        assert len(vs) == len(cargar(E).numerados) == 90

    def test_la_etiqueta_lleva_el_nombre_del_indicador(self):
        """Es lo que el agente lee para saber QUÉ buscar."""
        vs = {s.key: s for s in LawProduct().variable_signals()["signals"]}
        assert "corrupción" in vs["1.2"].label.lower()
        assert vs["1.2"].label.startswith("1.2 ")

    def test_real_si_y_solo_si_hay_binding_verificado(self):
        from shared.registry.signals import REAL
        from modules.law_intel.bindings import cargar_bindings
        bs = cargar_bindings(E)
        for s in LawProduct().variable_signals()["signals"]:
            b = bs.get(s.key)
            assert (s.state == REAL) is bool(b and b.cuenta), s.key

    def test_el_peso_es_uniforme(self):
        """La ley no jerarquiza sus metas: repartir pesos por criterio propio inventaría una
        prioridad que el legislador no fijó."""
        pesos = {s.weight for s in LawProduct().variable_signals()["signals"]}
        assert len(pesos) == 1

    def test_la_cobertura_del_eje_coincide_con_la_del_expediente(self):
        from shared.registry.signals import AxisRegistry
        from modules.law_intel.bindings import cobertura
        ax = AxisRegistry(sector_key="law", display_name="x", source="y", implemented=True,
                          signals=tuple(LawProduct().variable_signals()["signals"]))
        assert ax.coverage_real == pytest.approx(cobertura(E)["pct"] / 100.0, abs=0.001)


class TestElDetalleDeLaBrechaNombraIndicadores:
    """`detail` no es decorativo: el readiness lo inserta LITERALMENTE en el texto de la
    brecha, y de ahí lo lee el agente de descubrimiento de fuentes.

    Vacío, el agente recibía «faltan dimensiones con dato real ()» y sólo podía proponer
    fuentes genéricas del país — gastar en ruido.
    """

    def test_nombra_indicadores_concretos(self):
        """Se comprueba contra el estado REAL del expediente y no contra un indicador
        elegido a mano. La primera versión de este test fijaba el 1.1 como ejemplo, y el día
        que el 1.1 se midió el test se puso rojo sin que nada estuviera mal: lo que probaba
        era que ese indicador seguía sin medir, no que el detalle nombrara indicadores."""
        from modules.law_intel.bindings import cargar_bindings
        from modules.law_intel.registro import cargar

        bs = cargar_bindings(E)
        sin_medir = [i for i in cargar(E).numerados
                     if not ((b := bs.get(i.id)) and b.cuenta)]
        assert sin_medir, "no queda ninguno sin medir: el test dejó de probar algo"
        primero = sin_medir[0]
        d = LawProduct().data_signals().detail
        assert primero.id in d, d
        assert primero.nombre[:20] in d, d
        assert "()" not in d

    def test_dice_el_conteo_con_su_denominador(self):
        from modules.law_intel.bindings import cobertura
        c = cobertura(E)
        d = LawProduct().data_signals().detail
        assert f"{c['total'] - c['medidos']} de {c['total']}" in d

    def test_acota_cuantos_nombra(self):
        """Con 86 nombres el texto sería ilegible y el prompt se llenaría de ruido."""
        d = LawProduct().data_signals().detail
        assert "y " in d and "más" in d, "declara cuántos quedaron fuera de la muestra"
        assert len(d) < 1200

    def test_declara_la_cadencia_anual(self):
        """Sin declararla, el monitor penalizaría como obsoleta una fuente que por
        naturaleza publica una vez al año."""
        assert LawProduct().data_signals().cadence == "annual"


def test_el_vocabulario_obligatorio_distingue_estancada_de_retrocede():
    """Las dos suenan igual de mal y significan cosas distintas. Sin la glosa, el modelo
    redacta «retrocede» sobre una serie plana y el informe queda refutable con la fila de
    al lado — que es el defecto que este vocabulario existe para impedir."""
    from modules.law_intel.ai_context import GLOSA_ESTANCADA, law_ai_context

    voc = law_ai_context(E, "2025")["vocabulario_obligatorio"]
    assert voc["estancada"] == GLOSA_ESTANCADA
    assert "no escribas «retrocede»" in GLOSA_ESTANCADA.lower()


class TestLaAtribucionQueLaFuenteExige:
    """Hay fuentes admitidas cuya condición de uso es que se las nombre. La decisión de
    publicar así es del dueño (2026-08-22) y está registrada en el instrumento; estos tests
    la vuelven exigible en vez de recordable.

    El modo de falla que persiguen no es que la atribución esté mal escrita: es que
    DESAPAREZCA. Un texto obligatorio que vive en la cabeza del redactor se pierde en la
    primera reescritura, y nadie se entera hasta que el emisor reclama.
    """

    def test_la_obligacion_se_computa_de_la_fuente_y_no_de_una_lista(self):
        from modules.law_intel.ai_context import atribuciones_obligatorias
        from modules.law_intel.bindings import cargar_bindings
        from modules.law_intel.registro import cargar

        exigen = {f["id"] for f in cargar(E).meta["fuentes_admitidas"]
                  if f.get("exige_atribucion")}
        assert exigen, "ninguna fuente exige atribución: el barrido no probaría nada"
        esperados = {b.indicador for b in cargar_bindings(E).values()
                     if b.cuenta and b.fuente in exigen}
        assert {a["indicador"] for a in atribuciones_obligatorias(E)} == esperados

    def test_cada_atribucion_trae_su_texto(self):
        """Sin texto, la obligación es un aviso que no dice qué escribir."""
        from modules.law_intel.ai_context import atribuciones_obligatorias

        for a in atribuciones_obligatorias(E):
            assert len(a["atribucion"]) > 25, a

    def test_la_regla_llega_al_modelo_junto_con_la_lista(self):
        """La lista sin la regla se lee como información de contexto, no como obligación."""
        ctx = law_ai_context(E, "2025")
        assert ctx["atribuciones_obligatorias_por_indicador"]
        assert "NOMBRANDO a su fuente" in ctx["regla_de_la_atribucion"]

    def test_una_fuente_que_no_la_exige_no_aparece(self):
        """La obligación es de la fuente concreta, no de todas las externas: inflarla haría
        que el informe repitiera atribuciones que nadie pide y la regla perdería peso."""
        from modules.law_intel.ai_context import atribuciones_obligatorias

        fuentes = {a["fuente"] for a in atribuciones_obligatorias(E)}
        assert "wdi" not in fuentes and "bcrd" not in fuentes
