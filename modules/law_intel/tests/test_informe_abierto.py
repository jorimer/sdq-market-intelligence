"""El informe ABIERTO de una ley: el tercer entregable, y el único que se comparte.

Los dos primeros —informe técnico y dictamen— son confidenciales del cliente que los
encarga. Éste no tiene destinatario, y eso cambia dos cosas que los tests vigilan: el
REGISTRO (prosa externa, sin andamiaje de método) y lo que NO puede decir (el veredicto de
cumplimiento, que es lo que el cliente pagó).
"""
import pytest

from modules.law_intel.informe_abierto import (ADVERTENCIA_DEL_REGISTRO, DEUDOR_EN_PROSA,
                                               ESTADO_EN_PROSA, MARCA, SECCIONES_EN_ORDEN,
                                               TITULOS, _recortar, construir)
from modules.law_intel.registro import expedientes

EXPEDIENTES = expedientes()


@pytest.mark.parametrize("eid", EXPEDIENTES)
class TestSirveACUALQUIERley:
    def test_construye_sin_romperse(self, eid):
        """Una ley de obligaciones sin indicadores y una de 90 indicadores tienen que salir
        las dos: es el mismo seam que probó el expediente de la 167-21."""
        d = construir(eid)
        assert d["titulo"] and d["tablas"]

    def test_siempre_trae_la_tabla_de_ALCANCE(self, eid):
        assert construir(eid)["tablas"][0][0] == "Alcance de la medición"

    def test_las_secciones_OBLIGATORIAS_estan_y_tienen_texto(self, eid):
        """Cuatro salen siempre. Las otras dos —lo que declara el emisor, cuándo se
        actualiza— dependen de que la ley las tenga: inventarlas vacías sería peor que no
        tenerlas, porque una sección vacía se lee como que no hay nada que decir."""
        sec = construir(eid)["secciones"]
        for k in ("que_es", "lo_que_ordena", "lo_que_se_mide", "alcance"):
            assert sec.get(k, "").strip(), f"la sección «{k}» sale vacía"

    def test_ninguna_seccion_PRESENTE_sale_vacia(self, eid):
        sec = construir(eid)["secciones"]
        vacias = [k for k, v in sec.items() if not str(v).strip()]
        assert not vacias, f"secciones presentes y vacías: {vacias}"

    def test_las_secciones_salen_en_el_ORDEN_declarado(self, eid):
        sec = construir(eid)["secciones"]
        assert set(sec) <= set(SECCIONES_EN_ORDEN), (
            f"secciones sin lugar en el orden: {set(sec) - set(SECCIONES_EN_ORDEN)}")

    def test_toda_seccion_tiene_TITULO(self, eid):
        assert set(SECCIONES_EN_ORDEN) <= set(TITULOS)


@pytest.mark.parametrize("eid", EXPEDIENTES)
class TestElREGISTROesEXTERNO:
    """El lector está fuera de SDQ: ve la conclusión en prosa, no el método por su nombre."""

    def test_no_aparece_andamiaje_de_METODO(self, eid):
        d = construir(eid)
        texto = " ".join(d["secciones"].values())
        for molde in ("BLUF", "Bottom Line", "Hallazgo crítico", "Hallazgo de alto",
                      "Severidad:", "Lectura SDQ"):
            assert molde not in texto, f"«{molde}» es andamiaje interno y no sale del edificio"

    def test_el_vocabulario_INTERNO_se_traduce(self, eid):
        """`sin_registro_publico` y `universo` son jerga nuestra; el lector no tiene por qué
        conocer nuestro esquema."""
        filas = [f for t in construir(eid)["tablas"] for f in t[1]]
        crudo = {"sin_registro_publico", "cumplida_tarde", "pendiente_no_vencida",
                 "universo", "indeterminado", "organo"}
        for fila in filas:
            assert not (set(str(c) for c in fila) & crudo), f"jerga sin traducir en {fila}"

    def test_TODO_estado_del_expediente_tiene_traduccion(self, eid):
        from modules.law_intel.obligaciones import ESTADOS, cargar_obligaciones
        for o in cargar_obligaciones(eid):
            assert o.estado in ESTADO_EN_PROSA, f"estado «{o.estado}» sin prosa declarada"
            assert o.deudor["tipo"] in DEUDOR_EN_PROSA
        assert set(ESTADOS) <= set(ESTADO_EN_PROSA), (
            "un estado nuevo del vocabulario saldría crudo en un documento que se comparte")


@pytest.mark.parametrize("eid", EXPEDIENTES)
class TestLoQueNOpuedeDecir:
    def test_no_publica_el_VEREDICTO_de_cumplimiento(self, eid):
        """Ese análisis se prepara por encargo. Publicarlo el mismo día en un documento
        abierto le quita al cliente lo que pagó."""
        texto = " ".join(construir(eid)["secciones"].values()).lower()
        for palabra in ("alcanzó su meta", "no alcanzará", "incumple la meta",
                        "tasa de cumplimiento"):
            assert palabra not in texto

    def test_la_advertencia_del_registro_ACOMPAÑA_a_las_obligaciones(self, eid):
        """«No se encontró registro» y «no se hizo» son afirmaciones distintas."""
        d = construir(eid)
        if any(t[0] == "Qué ordena la norma" for t in d["tablas"]):
            assert ADVERTENCIA_DEL_REGISTRO in d["secciones"]["lo_que_ordena"]

    def test_la_marca_dice_que_se_COMPARTE(self, eid):
        assert "abierto" in MARCA.lower()


class TestElRECORTEnoParteLasPalabras:
    def test_corta_en_el_ultimo_espacio(self):
        """«dentro de quinc» y «vigencia d» se imprimen tal cual en la tabla."""
        assert _recortar("Evaluar el análisis dentro de quince días hábiles", 26) == \
            "Evaluar el análisis…"

    def test_no_toca_lo_que_ya_entra(self):
        assert _recortar("corto", 40) == "corto"

    def test_colapsa_los_espacios_del_expediente(self):
        assert _recortar("dos   espacios", 40) == "dos espacios"


def test_el_nombre_del_archivo_DISTINGUE_la_norma():
    """Dos leyes producían el mismo archivo y la segunda descarga pisaba a la primera."""
    from shared.products.filenames import report_filename
    nombres = {report_filename(naturaleza="Informe-Abierto", sector_key="law",
                               sujeto=n, periodo="2026-08-25", fmt="pdf")
               for n in ("Ley 167-21", "Ley 1-12", "Decreto 337-24")}
    assert len(nombres) == 3


def test_la_ruta_esta_registrada():
    import modules.law_intel.api.router as r
    assert any("informe-abierto" in x.path for x in r.router.routes)


class TestLoQueDeclaraElEMISOR:
    """«No hay dato» y «el organismo tiene el dato y declaró que no lo publica todavía» son
    cosas distintas. La segunda no es una brecha de nadie: es una decisión con fecha."""

    def test_la_167_21_recoge_las_declaraciones_del_MAP(self):
        from modules.law_intel.declaraciones import cargar
        ds = {d.id for d in cargar("ley_167_21")}
        assert "sismap-burocracia-cero-reservado" in ds

    def test_una_ley_sin_declaraciones_NO_inventa_la_seccion(self):
        d = construir("end_2030")
        assert "lo_que_declara_el_emisor" not in d["secciones"]

    def test_cada_declaracion_llega_con_su_FECHA_y_su_AUTOR(self):
        texto = construir("ley_167_21")["secciones"]["lo_que_declara_el_emisor"]
        assert "2026-03-12" in texto and "Ministerio de Administración Pública" in texto

    def test_cada_declaracion_llega_con_su_CONSECUENCIA(self):
        """Citar lo que dijo el emisor sin decir qué implica deja al lector con una noticia."""
        texto = construir("ley_167_21")["secciones"]["lo_que_declara_el_emisor"]
        assert "no es una brecha de información" in texto.lower()

    def test_una_declaracion_sin_fuente_NO_carga(self):
        from modules.law_intel.declaraciones import Declaracion, _validar
        from modules.law_intel.registro import ExpedienteInvalido
        d = Declaracion(id="x", fecha="2026-01-01", quien="Alguien",
                        que_declara="algo", fuente="",
                        consecuencia_para_la_medicion="implica algo")
        with pytest.raises(ExpedienteInvalido, match="rumor"):
            _validar([d])

    def test_una_declaracion_sin_CONSECUENCIA_no_carga(self):
        from modules.law_intel.declaraciones import Declaracion, _validar
        from modules.law_intel.registro import ExpedienteInvalido
        d = Declaracion(id="x", fecha="2026-01-01", quien="Alguien", que_declara="algo",
                        fuente="http://x", consecuencia_para_la_medicion="")
        with pytest.raises(ExpedienteInvalido, match="noticia"):
            _validar([d])


class TestCuandoSeActualiza:
    """La cadencia sale de la AGENDA, no de una frase escrita a mano que envejece."""

    class _Fila:
        def __init__(self):
            import datetime as _d
            self.operation = "tramites-registro-unico"
            self.enabled = True
            self.interval_hours = 730
            self.next_run_at = _d.datetime(2026, 9, 25, 9, 55)
            self.last_run_at = _d.datetime(2026, 8, 25, 23, 55)

    class _DB:
        def query(self, *a, **k):
            return self

        def filter(self, *a, **k):
            return self

        def all(self):
            return [TestCuandoSeActualiza._Fila()]

    def test_dice_cada_cuanto_y_cuando_toca(self):
        from modules.law_intel.informe_abierto import _cuando_se_actualiza
        t = _cuando_se_actualiza("ley_167_21", self._DB(), leido_el="2026-08-26")
        assert "cada 30 días" in t
        assert "2026-09-25" in t

    def test_la_fecha_de_la_AGENDA_no_se_publica_como_la_del_dato(self):
        """El `last_run_at` de la agenda dice cuándo corrió la operación, no cuándo se leyó
        el dato. Una corrida manual las separa, y el informe publicó la de la agenda."""
        from modules.law_intel.informe_abierto import _cuando_se_actualiza
        t = _cuando_se_actualiza("ley_167_21", self._DB(), leido_el="2026-08-26")
        assert "La lectura que se publica acá es del 2026-08-26" in t
        assert "2026-08-25" not in t

    def test_una_ley_SIN_serie_de_seguimiento_no_promete_actualizacion(self):
        from modules.law_intel.informe_abierto import _cuando_se_actualiza
        assert _cuando_se_actualiza("end_2030", self._DB()) is None

    def test_TODA_serie_declarada_tiene_su_operacion_MAPEADA(self):
        """El guard del mapa a mano: una serie nueva sin entrada deja el informe sin
        prometer actualización, en silencio."""
        from modules.law_intel.informe_abierto import OPERACION_QUE_ALIMENTA
        from modules.law_intel.obligaciones import cargar_obligaciones
        from modules.law_intel.registro import expedientes
        faltan = []
        for eid in expedientes():
            for o in cargar_obligaciones(eid):
                if o.serie_de_seguimiento and o.serie_de_seguimiento not in OPERACION_QUE_ALIMENTA:
                    faltan.append(f"{eid}:{o.serie_de_seguimiento}")
        assert not faltan, f"series de seguimiento sin operación declarada: {faltan}"

    def test_las_operaciones_del_mapa_EXISTEN(self):
        """Un nombre mal escrito acá se ve igual que «no hay agenda»."""
        import modules.social_dev.operations  # noqa: F401 — registra al importar
        from shared.operations.service import OPERATIONS

        from modules.law_intel.informe_abierto import OPERACION_QUE_ALIMENTA
        faltan = [n for n in set(OPERACION_QUE_ALIMENTA.values()) if n not in OPERATIONS]
        assert not faltan, f"operaciones declaradas que no existen: {faltan}"


class TestElAnexoDeEVIDENCIA:
    """La 167-21 tiene una serie que la sigue y las otras no. Un renderizador que adivinara
    cuál anexo aplicar acabaría poniéndole a una ley la evidencia de otra."""

    class _Fila:
        def __init__(self, theme, value, period="2026-08"):
            self.theme, self.value, self.period = theme, value, period
            self.entity_key, self.disaggregation = "nacional", "nacional"
            # La misma sesión de mentira atiende dos consultas —la del anexo y la de la
            # agenda—. Se declara `enabled=False` para que la de la agenda descarte estas
            # filas en vez de reventar: el test del anexo prueba el anexo, no la cadencia.
            self.enabled, self.interval_hours = False, None

    class _DB:
        def __init__(self, filas):
            self._f = filas

        def query(self, *a, **k):
            return self

        def filter(self, *a, **k):
            return self

        def all(self):
            return self._f

    def _db(self):
        from modules.social_dev.tramites_sync import (TEMA_CON_TIEMPO, TEMA_PCT, TEMA_TOTAL)
        return self._DB([self._Fila(TEMA_TOTAL, 710.0),
                         self._Fila(TEMA_CON_TIEMPO, 22.0),
                         self._Fila(TEMA_PCT, 3.1)])

    def test_la_167_21_trae_el_anexo_del_catalogo(self):
        titulos = [t[0] for t in construir("ley_167_21", self._db())["tablas"]]
        assert any("catálogo de trámites" in t for t in titulos)

    def test_el_titulo_del_anexo_NOMBRA_el_periodo(self):
        """Una tabla sin fecha de lectura sobre un catálogo vivo se lee como si fuera de hoy
        para siempre."""
        t = [x for x in construir("ley_167_21", self._db())["tablas"]
             if "catálogo" in x[0]][0]
        assert "2026-08" in t[0]

    def test_las_otras_leyes_NO_reciben_ese_anexo(self):
        for eid in ("end_2030", "meta_rd_2036"):
            titulos = [t[0] for t in construir(eid, self._db())["tablas"]]
            assert not any("catálogo de trámites" in t for t in titulos)

    def test_sin_serie_persistida_el_anexo_NO_sale(self):
        """Un anexo vacío afirmaría que el catálogo está vacío."""
        titulos = [t[0] for t in construir("ley_167_21", self._DB([]))["tablas"]]
        assert not any("catálogo" in t for t in titulos)

    def test_toda_ley_del_ANEXO_existe_en_el_catalogo(self):
        from modules.law_intel.registro import expedientes

        from modules.law_intel.informe_abierto import ANEXOS_POR_EXPEDIENTE
        faltan = [e for e in ANEXOS_POR_EXPEDIENTE if e not in expedientes()]
        assert not faltan, f"anexos declarados para expedientes que no existen: {faltan}"


class TestLaPROSAquesEIMPRIME:
    """Se comparte: una concordancia rota le dice al lector que nadie lo leyó."""

    @pytest.mark.parametrize("eid", EXPEDIENTES)
    def test_ninguna_seccion_dice_UNO_en_plural(self, eid):
        texto = " ".join(construir(eid)["secciones"].values())
        for roto in ("De los 1 ", "Los 1 restantes", "1 indicadores", "1 obligaciones",
                     "los 1 indicadores"):
            assert roto not in texto, f"concordancia rota: «{roto}»"

    @pytest.mark.parametrize("eid", EXPEDIENTES)
    def test_el_titular_CONCUERDA(self, eid):
        from modules.law_intel.informe_abierto import _titular
        t = _titular(construir(eid)["titulares"])
        assert "1 indicadores" not in t and "1 obligaciones" not in t

    def test_el_titular_de_una_ley_de_OBLIGACIONES_no_habla_de_indicadores(self):
        """«Mide 0 de 1 indicadores» es cierto y se lee como un fracaso: la 167-21 no es una
        ley de metas. Titular por indicadores le pone una vara que su objeto no admite."""
        from modules.law_intel.informe_abierto import _titular
        assert _titular({"medidos": 0, "total": 1, "obligaciones": 10}) == \
            "10 obligaciones con deudor y plazo"

    def test_el_titular_de_una_ley_de_METAS_sí(self):
        from modules.law_intel.informe_abierto import _titular
        assert _titular({"medidos": 46, "total": 90, "obligaciones": 7}) == \
            "Mide 46 de 90 indicadores"


class TestElDetalleDelAnexo:
    """Las tablas que hacen que el anexo diga algo, y los dos errores que casi publica."""

    class _Fila:
        def __init__(self, theme, value, entity="nacional", nota="nacional",
                     period="2026-08"):
            self.theme, self.value, self.entity_key = theme, value, entity
            self.disaggregation, self.period = nota, period
            self.enabled, self.interval_hours = False, None

    class _DB:
        def __init__(self, filas):
            self._f, self._t, self._p = filas, None, None

        def query(self, *a, **k):
            self._t = None
            return self

        def filter(self, *cond, **k):
            # El doble filtra por el tema que pide cada consulta. `str(expr)` de SQLAlchemy
            # NO trae el valor —renderiza `theme = :theme_1`—, así que hay que compilar con
            # los literales o el doble devuelve TODAS las filas a TODAS las consultas y las
            # tablas salen mezcladas sin que ningún test lo note.
            for c in cond:
                txt = str(c.compile(compile_kwargs={"literal_binds": True}))
                # Los literales de la CONSULTA, no los temas que el doble tiene. Filtrar
                # contra las filas existentes hace que una consulta por un tema sin filas no
                # restrinja nada y devuelva todas: así el nombre del trámite salía de la
                # serie de tiempos y la tabla imprimía «3 horas» en la columna del nombre.
                import re as _re
                if ".theme" not in txt:
                    continue
                pedidos = set(_re.findall(r"'([a-z_]+)'", txt))
                self._t = pedidos if self._t is None else (self._t & pedidos)
            return self

        def all(self):
            return [f for f in self._f if self._t is None or f.theme in self._t]

    def _db(self):
        from modules.social_dev.tramites_sync import (TEMA_CON_TIEMPO,
                                                      TEMA_CON_TIEMPO_POR_INSTITUCION,
                                                      TEMA_CONSULTAS_POR_INSTITUCION,
                                                      TEMA_PCT, TEMA_POR_INSTITUCION,
                                                      TEMA_TIEMPO_POR_TRAMITE, TEMA_TOTAL)
        F = self._Fila
        return self._DB([
            F(TEMA_TOTAL, 710.0), F(TEMA_CON_TIEMPO, 22.0), F(TEMA_PCT, 3.1),
            F(TEMA_POR_INSTITUCION, 23.0, "DGP", "por institución"),
            F(TEMA_POR_INSTITUCION, 11.0, "Supérate", "por institución"),
            F(TEMA_CONSULTAS_POR_INSTITUCION, 85432.0, "DGP", "por institución"),
            F(TEMA_CONSULTAS_POR_INSTITUCION, 1535542.0, "Supérate", "por institución"),
            F(TEMA_CON_TIEMPO_POR_INSTITUCION, 14.0, "DGP", "por institución"),
            F(TEMA_CON_TIEMPO_POR_INSTITUCION, 0.0, "Supérate", "por institución"),
            F(TEMA_TIEMPO_POR_TRAMITE, 0.125, "pasaporte-1", "DGP · 3 horas · perifrasis"),
            F(TEMA_TIEMPO_POR_TRAMITE, 0.125, "pasaporte-2", "DGP · 3 horas · perifrasis"),
            F(TEMA_TIEMPO_POR_TRAMITE, 5.0, "cnzfe-1", "CNZFE · 5 días laborables · explicito"),
            F("tramites_consultas_por_tramite", 500.0, "pasaporte-1",
              "DGP · Renovación Pasaporte"),
            F("tramites_consultas_por_tramite", 450.0, "pasaporte-2",
              "DGP · Renovación Pasaporte Menor"),
            F("tramites_consultas_por_tramite", 400.0, "cnzfe-1",
              "CNZFE · Cambio de Nombre Empresas"),
        ])

    def _tabla(self, titulo):
        t = [x for x in construir("ley_167_21", self._db())["tablas"] if titulo in x[0]]
        return t[0] if t else None

    def test_las_instituciones_se_ordenan_por_CONSULTAS(self):
        """Una con 61 trámites y otra con 1,5 millones de consultas no pesan igual para
        quien espera."""
        filas = self._tabla("instituciones más consultadas")[1][1:]
        assert filas[0][0] == "Supérate"

    def test_la_columna_de_declara_dice_la_VERDAD(self):
        """El primer intento tenía una caché que nunca se llenaba: la columna habría dicho
        «No» para todas, afirmando que ninguna institución declara nada."""
        filas = {f[0]: f[3] for f in self._tabla("instituciones más consultadas")[1][1:]}
        assert filas["DGP"] == "Sí" and filas["Supérate"] == "No"

    def test_cada_trámite_va_con_su_NOMBRE(self):
        """Agrupar por institución y plazo daba una tabla compacta y equivocada: el
        documento afirma que 22 declaran su tiempo y no decía CUÁLES ni qué hace cada uno,
        que es lo único que vuelve comprobable la afirmación."""
        filas = self._tabla("declaran cuánto tardan")[1][1:]
        assert ["Renovación Pasaporte", "DGP", "3 horas", "Lo dice en prosa"] in filas
        assert len(filas) == 3, "una fila por trámite, no una por grupo"

    def test_el_NOMBRE_no_sale_de_la_serie_de_tiempos(self):
        """El doble devolvía todas las filas a la consulta por consultas y la columna del
        nombre imprimía «3 horas». Un doble que no restringe convierte un test en adorno."""
        filas = self._tabla("declaran cuánto tardan")[1][1:]
        assert not any(f[0] == f[2] for f in filas)

    def test_el_slug_NO_se_imprime_cuando_hay_nombre(self):
        """«pasaporte-1» no es lo que nadie busca. El nombre se une por slug desde la serie
        de consultas, que es la que lo trae."""
        filas = self._tabla("declaran cuánto tardan")[1][1:]
        assert not any(f[0].startswith("pasaporte-") for f in filas)

    def test_sin_nombre_en_la_serie_cae_al_SLUG_y_no_a_vacío(self):
        """Una fila sin nombre con la celda en blanco se lee como si el trámite no
        existiera. El slug es feo pero identifica."""
        db = self._db()
        db._f = [f for f in db._f if f.theme != "tramites_consultas_por_tramite"]  # noqa: E501
        t = [x for x in construir("ley_167_21", db)["tablas"]
             if "declaran cuánto tardan" in x[0]][0]
        assert all(f[0].strip() for f in t[1][1:])
        assert any(f[0].startswith("pasaporte-") for f in t[1][1:])

    def test_ordena_por_INSTITUCION_y_después_por_nombre(self):
        """Las fichas de una misma institución se leen juntas, y el orden es estable entre
        corridas — si no, dos descargas del mismo día dan tablas distintas."""
        filas = self._tabla("declaran cuánto tardan")[1][1:]
        assert [f[1] for f in filas] == sorted(f[1] for f in filas)

    def test_distingue_NOMBRAR_el_campo_de_decirlo_en_prosa(self):
        """La Resolución 142-2024 exige un campo; una perífrasis lo suple sin cumplirlo."""
        filas = self._tabla("declaran cuánto tardan")[1][1:]
        niveles = {f[1]: f[3] for f in filas}
        assert niveles["CNZFE"] == "Nombra el campo"
        assert niveles["DGP"] == "Lo dice en prosa"

    def test_el_titulo_lleva_los_DOS_denominadores(self):
        assert "3 de 710" in self._tabla("declaran cuánto tardan")[0]

    def test_el_numerador_del_titulo_CUENTA_las_filas_de_la_tabla(self):
        """Contar las filas de la serie en vez de las de la tabla afirma un total que la
        tabla debajo no muestra: la fila con la nota malformada se salta al armarla."""
        t = self._tabla("declaran cuánto tardan")
        n = int(t[0].split("(")[1].split(" de")[0])
        assert n == len(t[1]) - 1

    def test_la_notacion_de_miles_es_ESPAÑOLA(self):
        filas = self._tabla("instituciones más consultadas")[1][1:]
        assert filas[0][2] == "1.535.542"


class TestLasTablasVanDESPUESdelTexto:
    """Un informe que abre con seis páginas de tablas antes de una sola frase se lee como un
    anexo: el lector externo llega a los 22 trámites sin saber todavía qué se le está
    midiendo ni con qué criterio. Pedido del dueño, el mismo que ya se había hecho sobre el
    informe de brand_intel."""

    def test_render_pasa_tables_last(self, monkeypatch):
        visto = {}
        monkeypatch.setattr("shared.products.render.render_product_pdf",
                            lambda **k: (visto.update(k), "/tmp/x.pdf")[1])
        from modules.law_intel.informe_abierto import render
        render("ley_167_21", db=None, fmt="pdf")
        assert visto.get("tables_last") is True

    def test_el_renderizador_compartido_SIGUE_soportando_la_opción(self):
        """Si alguien quita el parámetro del renderizador compartido, este producto vuelve a
        abrir con tablas y nadie lo nota hasta que el dueño lo lee."""
        import inspect

        from shared.products.render import render_product_pdf
        assert "tables_last" in inspect.signature(render_product_pdf).parameters
