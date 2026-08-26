"""El anexo no son solo tablas: dice con qué criterio se contó y qué NO afirma.

Los tres huecos que cerró este archivo salieron de comparar el informe que arma la
plataforma contra uno escrito a mano: el documento a mano explicaba el criterio de
extracción, sus límites propios y el rango de cada disposición, y la plataforma publicaba
las cifras sin nada de eso. Una tabla cuyo método quedó en otro documento no es verificable.
"""
import pytest

from modules.law_intel.informe_abierto import (ANEXOS_POR_EXPEDIENTE, Anexo, LIMITES_TRAMITES,
                                               _metodologia_tramites, construir)


class _Fila:
    def __init__(self, theme, value, entity="nacional", nota="nacional", period="2026-08"):
        self.theme, self.value, self.entity_key = theme, value, entity
        self.disaggregation, self.period = nota, period
        self.enabled, self.interval_hours = False, None


class _DB:
    """Devuelve solo las filas del tema que la consulta pide.

    `str(expr)` de SQLAlchemy NO trae el valor —renderiza `theme = :theme_1`—, así que hay
    que compilar con los literales o el doble devuelve TODAS las filas a TODAS las consultas.
    """

    def __init__(self, filas):
        self._f, self._t = filas, None

    def query(self, *a, **k):
        self._t = None
        return self

    def filter(self, *cond, **k):
        import re
        for c in cond:
            txt = str(c.compile(compile_kwargs={"literal_binds": True}))
            if ".theme" not in txt:
                continue
            # Los literales de la consulta, NO los temas que el doble tiene. Filtrar contra
            # las filas existentes hace que una consulta por un tema sin filas no restrinja
            # nada y devuelva todas: el caso «la serie no existe todavía» quedaba sin probar.
            pedidos = set(re.findall(r"'([a-z_]+)'", txt))
            self._t = pedidos if self._t is None else (self._t & pedidos)
        return self

    def all(self):
        return [f for f in self._f if self._t is None or f.theme in self._t]


def _temas():
    from modules.social_dev.tramites_sync import (TEMA_CIFRA_SIN_ANCLAR, TEMA_CON_TIEMPO,
                                                  TEMA_CONSULTAS_POR_INSTITUCION,
                                                  TEMA_CONSULTAS_POR_TRAMITE, TEMA_PCT,
                                                  TEMA_POR_INSTITUCION,
                                                  TEMA_CON_TIEMPO_POR_INSTITUCION,
                                                  TEMA_TIEMPO_POR_TRAMITE, TEMA_TOTAL)
    return locals()


def _db(con_contrafactual=True, con_consultas=True):
    t = _temas()
    filas = [_Fila(t["TEMA_TOTAL"], 710.0), _Fila(t["TEMA_CON_TIEMPO"], 22.0),
             _Fila(t["TEMA_PCT"], 3.1),
             _Fila(t["TEMA_POR_INSTITUCION"], 11.0, "Supérate", "por institución"),
             _Fila(t["TEMA_CONSULTAS_POR_INSTITUCION"], 1535557.0, "Supérate", "por institución"),
             _Fila(t["TEMA_CON_TIEMPO_POR_INSTITUCION"], 0.0, "Supérate", "por institución"),
             _Fila(t["TEMA_TIEMPO_POR_TRAMITE"], 5.0, "cnzfe-1",
                   "CNZFE · 5 días laborables · explicito")]
    if con_contrafactual:
        filas.append(_Fila(t["TEMA_CIFRA_SIN_ANCLAR"], 165.0))
    if con_consultas:
        filas += [_Fila(t["TEMA_CONSULTAS_POR_TRAMITE"], 1535557.0, "consultas-superate",
                        "Supérate · Consultas Supérate"),
                  _Fila(t["TEMA_CONSULTAS_POR_TRAMITE"], 136924.0, "pruebas-nacionales",
                        "MINERD · Consulta Resultados de Pruebas Nacionales")]
    return _DB(filas)


class TestLaRazonSeCOMPUTA:
    """«Cinco veces mayor» estaba escrito a mano sobre una medición de un día. En cuanto el
    criterio estrecho pasó de 3 a 22 la frase quedó falsa y nadie se enteró leyendo."""

    def test_dice_cuantas_veces_MAS_seria_con_criterio_laxo(self):
        m = _metodologia_tramites(_db(), "2026-08", 710.0)
        assert "de 22 a 165 de 710 fichas, 7,5 veces más" in m

    def test_la_razon_usa_COMA_como_el_resto_del_documento(self):
        assert "7,5" in _metodologia_tramites(_db(), "2026-08", 710.0)
        assert "7.5 veces" not in _metodologia_tramites(_db(), "2026-08", 710.0)

    def test_una_razon_ENTERA_no_finge_una_decimal(self):
        """«9,0 veces más» se lee como una precisión que la cifra no tiene."""
        db = _db()
        for f in db._f:
            if f.theme == "tramites_mencionan_cifra_de_tiempo_sin_anclar":
                f.value = 198.0                             # 198 / 22 = 9 exacto
        m = _metodologia_tramites(db, "2026-08", 710.0)
        assert "9 veces más" in m and "9,0 veces" not in m

    def test_SIN_el_contrafactual_no_se_afirma_la_razon(self):
        """Un período viejo, persistido antes de que la serie existiera, no tiene el dato.
        Inventar la comparación sería peor que omitirla."""
        m = _metodologia_tramites(_db(con_contrafactual=False), "2026-08", 710.0)
        assert "veces más" not in m
        assert "criterio deliberadamente estrecho" in m

    def test_nombra_lo_que_el_criterio_DESCARTA(self):
        """Sin decir qué son esas 143 fichas de más, el lector no puede juzgar el criterio."""
        m = _metodologia_tramites(_db(), "2026-08", 710.0)
        assert "multas" in m and "vigencias de documentos" in m


class TestLosMasConsultados:
    def test_la_tabla_imprime_el_NOMBRE_y_no_el_slug(self):
        """«consultas-superate» no es como nadie busca el trámite."""
        t = [x for x in construir("ley_167_21", _db())["tablas"]
             if "más consulta la gente" in x[0]][0]
        assert t[1][1][0] == "Consultas Supérate"
        assert "superate-" not in " ".join(t[1][1])

    def test_ordena_por_CONSULTAS_descendente(self):
        t = [x for x in construir("ley_167_21", _db())["tablas"]
             if "más consulta la gente" in x[0]][0]
        assert [f[2] for f in t[1][1:]] == ["1.535.557", "136.924"]

    def test_el_titulo_dice_que_es_un_CORTE_y_de_cuantos(self):
        """Un «top 10» sin denominador se lee como si fueran todos los trámites."""
        t = [x for x in construir("ley_167_21", _db())["tablas"]
             if "más consulta la gente" in x[0]][0]
        assert "los 2 primeros de 2" in t[0]

    def test_va_DESPUES_del_catalogo_y_ANTES_de_los_tiempos(self):
        titulos = [x[0] for x in construir("ley_167_21", _db())["tablas"]]
        i = [n for n, t in enumerate(titulos) if "más consulta la gente" in t][0]
        assert "catálogo de trámites" in titulos[i - 1]
        assert any("declaran cuánto tardan" in t for t in titulos[i + 1:])

    def test_sin_la_serie_no_hay_tabla_y_el_informe_SALE(self):
        """Un período persistido antes de que la serie existiera no debe tumbar el informe."""
        titulos = [x[0] for x in construir("ley_167_21", _db(con_consultas=False))["tablas"]]
        assert not any("más consulta la gente" in t for t in titulos)
        assert any("catálogo de trámites" in t for t in titulos)


class TestLosLimitesPROPIOSdelDato:
    def test_van_ANTES_del_descargo_generico(self):
        """Quien llega al alcance quiere saber qué no afirma ESTE informe, no la nota que
        sirve para cualquier ley."""
        a = construir("ley_167_21", _db())["secciones"]["alcance"]
        assert a.index("No audita si el tiempo declarado") < a.index("no audita la exactitud")

    def test_dicen_que_no_se_audita_el_CUMPLIMIENTO_del_plazo(self):
        assert "se cumple en la práctica" in LIMITES_TRAMITES

    def test_dicen_que_no_se_reviso_institucion_por_institucion(self):
        assert "institución por institución" in LIMITES_TRAMITES

    def test_una_ley_SIN_anexo_conserva_su_alcance_generico(self):
        a = construir("end_2030", None)["secciones"]["alcance"]
        assert "no audita la exactitud" in a
        assert "el tiempo declarado" not in a


class TestElContratoDelAnexo:
    def test_todo_anexo_declarado_devuelve_un_Anexo(self):
        """El anexo dejó de ser una lista de tablas para poder traer su método y sus
        límites. Un expediente que devuelva una lista rompe el informe en ejecución."""
        for eid, arma in ANEXOS_POR_EXPEDIENTE.items():
            assert isinstance(arma(_db()), Anexo), eid

    def test_las_secciones_nuevas_estan_TITULADAS(self):
        from modules.law_intel.informe_abierto import SECCIONES_EN_ORDEN, TITULOS
        for k in ("lectura_juridica", "como_se_obtuvo"):
            assert k in SECCIONES_EN_ORDEN, f"«{k}» no se renderiza"
            assert TITULOS.get(k), f"«{k}» sin título: sale como un bloque sin encabezado"

    @pytest.mark.parametrize("seccion", ("como_se_obtuvo", "lectura_juridica", "alcance"))
    def test_sin_andamiaje_de_metodo(self, seccion):
        s = construir("ley_167_21", _db())["secciones"][seccion].lower()
        assert not any(x in s for x in ("hallazgo crítico", "bluf", "severidad"))


class TestElGuardESTRUCTURAL:
    """Un anexo NUEVO no puede publicar cifras sin decir con qué criterio se obtuvieron.

    La lección escrita no alcanza: este mismo repositorio publicó tres tablas de trámites
    durante un día sin una línea de método, porque el método vivía en un documento escrito
    a mano que nadie volvió a mirar. El día que alguien registre el anexo de la ley
    siguiente va a copiar la forma, no el párrafo del docstring.
    """

    def test_todo_anexo_del_registro_declara_METODO_y_LIMITES(self):
        for eid, arma in ANEXOS_POR_EXPEDIENTE.items():
            a = arma(_db())
            if not a.tablas:
                continue
            assert (a.metodologia or "").strip(), (
                f"«{eid}» publica {len(a.tablas)} tabla(s) y no dice cómo se obtuvieron. "
                f"Una cifra sin su criterio no es verificable por quien la lee.")
            assert (a.limites or "").strip(), (
                f"«{eid}» publica {len(a.tablas)} tabla(s) y no dice qué NO afirman.")

    def test_toda_tabla_del_anexo_tiene_ENCABEZADO_y_al_menos_una_fila(self):
        """Una tabla vacía con título se imprime como un encabezado suelto, y el lector lo
        lee como que no hay nada — que es distinto de que no se haya podido leer."""
        for eid, arma in ANEXOS_POR_EXPEDIENTE.items():
            for titulo, filas in arma(_db()).tablas:
                assert titulo.strip(), eid
                assert len(filas) >= 2, f"«{eid}» → «{titulo}» sale sin filas"
                assert len(set(len(f) for f in filas)) == 1, (
                    f"«{eid}» → «{titulo}»: filas de anchos distintos rompen el render")
