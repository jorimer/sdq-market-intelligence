"""Cuándo manda la LEY que se mida — que no es cada cuánto lo relee nuestro sync.

El primer diseño de esta sección iba a publicar la cadencia de la operación que lee el dato.
Es la respuesta pobre: al lector le importa cada cuánto manda la NORMA evaluarse, porque eso
es exigible y lo otro es un detalle de nuestra implementación. La END lo fija con artículo,
deudor y fecha, y el expediente ya lo tenía como dato.
"""
import pytest

from modules.law_intel.informe_abierto import (CADA_CUANTO, SECCIONES_EN_ORDEN, TITULOS,
                                               _cortes_de_las_metas, _cuando_manda_la_ley_medir,
                                               _fechas_del_plazo, _lista_en_prosa, construir)
from modules.law_intel.obligaciones import cargar_obligaciones
from modules.law_intel.registro import ExpedienteInvalido, cargar, expedientes


class TestElHitoSeDECLARA:
    """Ni `periodicidad` ni `produce` sirven para inferirlo: la 167-21 tiene una obligación
    `continua` de publicar trámites —que es lo que se MIDE, no un momento de medir— y la END
    produce un `reglamento_de_aplicacion`, que es una norma."""

    def test_la_END_declara_sus_tres_hitos(self):
        hs = {o.articulo for o in cargar_obligaciones("end_2030") if o.hito_de_medicion}
        assert hs == {41, 42, 44}

    def test_la_167_21_no_declara_ninguno_y_eso_es_correcto(self):
        """Manda publicar los trámites de forma continua; no fija un calendario de
        evaluación de sí misma."""
        assert not [o for o in cargar_obligaciones("ley_167_21") if o.hito_de_medicion]

    def test_un_hito_SIN_fecha_es_rechazado(self):
        """Publicar «la ley manda medirse» sin decir cuándo deja al lector sin lo único
        accionable."""
        from modules.law_intel.obligaciones import Obligacion, _validar
        o = Obligacion(id="x", articulo=1, deber="d", deudor={"tipo": "organo"},
                       estado="cumplida", hito_de_medicion=True)
        with pytest.raises(ExpedienteInvalido, match="sin `periodicidad` ni `plazo`"):
            _validar([o])

    def test_TODO_hito_declarado_en_el_repo_tiene_fecha(self):
        """El guard sobre los expedientes reales, no sobre un objeto de laboratorio."""
        for eid in expedientes():
            for o in cargar_obligaciones(eid):
                if o.hito_de_medicion:
                    assert o.periodicidad or o.plazo, f"{eid}:{o.id}"


class TestLoQueLaSeccionDICE:
    def _seccion(self, eid="end_2030"):
        return construir(eid, None)["secciones"].get("cuando_manda_la_ley_medir")

    def test_nombra_los_CORTES_de_las_metas(self):
        s = self._seccion()
        assert "2015, 2020, 2025 y 2030" in s

    def test_advierte_que_se_juzga_contra_el_corte_QUE_CORRESPONDA(self):
        """Un indicador que va camino a 2030 puede estar incumpliendo el corte vigente."""
        s = self._seccion()
        assert "meta de 2030 puede estar incumpliendo la de 2025" in s

    def test_el_recuento_no_PIERDE_el_hito_que_no_venció(self):
        """Una primera versión decía «uno consta cumplido y otro no» sobre TRES hitos: el
        tercero desaparecía, y un hito no vencido es el que no hay que dar por perdido."""
        s = self._seccion()
        assert "1 consta cumplido y 1 no" in s
        assert "el restante todavía no vence" in s

    def test_dice_POR_QUE_uno_se_cumple_y_el_otro_no(self):
        assert "exige evaluación externa" in self._seccion()

    def test_una_ley_SIN_calendario_propio_no_tiene_la_seccion(self):
        """No se rellena con nuestra cadencia: que la ley no fije un calendario es
        información, no un hueco."""
        assert self._seccion("ley_167_21") is None

    def test_sin_andamiaje_de_metodo(self):
        s = self._seccion().lower()
        assert not any(x in s for x in ("hallazgo", "bluf", "severidad", "p0"))


class TestLaTABLA:
    def _tabla(self, eid="end_2030"):
        t = [x for x in construir(eid, None)["tablas"] if "manda evaluarse" in x[0]]
        return t[0] if t else None

    def test_trae_los_tres_articulos_en_orden(self):
        assert [f[0] for f in self._tabla()[1][1:]] == ["41", "42", "44"]

    def test_la_periodicidad_se_dice_en_CASTELLANO_corriente(self):
        """«cuatrienal» es vocabulario nuestro; el lector externo lee «cada cuatro años»."""
        filas = {f[0]: f[2] for f in self._tabla()[1][1:]}
        assert filas["41"] == "cada año" and filas["42"] == "cada cuatro años"

    def test_las_fechas_CIERTAS_se_listan_todas(self):
        """Ahí está el hallazgo: se ve de un vistazo cuántas pasaron sin cumplirse."""
        filas = {f[0]: f[3] for f in self._tabla()[1][1:]}
        assert filas["42"] == "2016, 2020, 2024, 2028"

    def test_una_fecha_ANUAL_se_lee_como_fecha_y_no_como_código(self):
        filas = {f[0]: f[3] for f in self._tabla()[1][1:]}
        assert filas["41"] == "antes del 5 de abril"

    def test_el_estado_va_en_PROSA_y_no_en_vocabulario_interno(self):
        filas = {f[0]: f[4] for f in self._tabla()[1][1:]}
        assert filas["42"] == "No realizada"
        assert "incumplida" not in " ".join(filas.values())

    def test_la_167_21_no_trae_la_tabla(self):
        assert self._tabla("ley_167_21") is None


class TestElORDEN:
    def test_lo_que_manda_la_LEY_va_antes_que_nuestra_cadencia(self):
        """Son dos preguntas distintas y la exigible va primero."""
        i = SECCIONES_EN_ORDEN.index("cuando_manda_la_ley_medir")
        assert i < SECCIONES_EN_ORDEN.index("cuando_se_actualiza")
        assert i > SECCIONES_EN_ORDEN.index("lo_que_ordena")

    def test_los_dos_titulos_se_DISTINGUEN(self):
        """«Cuándo se actualiza este informe» al lado de «cuándo manda la ley que se mida»
        se confunden, y confundirlas atribuye a la norma nuestra cadencia."""
        assert TITULOS["cuando_manda_la_ley_medir"] == "Cuándo manda la ley que se mida"
        assert "el dato de este informe" in TITULOS["cuando_se_actualiza"]

    def test_toda_seccion_del_orden_tiene_TITULO(self):
        for k in SECCIONES_EN_ORDEN:
            assert TITULOS.get(k), f"«{k}» saldría como un bloque sin encabezado"


class TestLosAYUDANTES:
    def test_los_cortes_salen_de_las_METAS_y_no_de_una_lista_escrita(self):
        """Transcribirlos los desincronizaría del día que se corrija uno."""
        assert _cortes_de_las_metas(cargar("end_2030")) == ["2015", "2020", "2025", "2030"]

    def test_un_expediente_sin_metas_no_inventa_cortes(self):
        assert _cortes_de_las_metas(cargar("ley_167_21")) == []

    @pytest.mark.parametrize("plazo,esperado", [
        ({"tipo": "fecha_anual", "vence": "04-05"}, "antes del 5 de abril"),
        ({"tipo": "fechas", "vence": ["2016-07-31", "2020-07-31"]}, "2016, 2020"),
        ({"tipo": "fecha_cierta", "vence": "2029-12-31"}, "2029-12-31"),
        (None, "—"),
        ({"tipo": "sin_plazo_legal"}, "—"),
    ])
    def test_el_plazo_se_imprime_sin_jerga_de_tipos(self, plazo, esperado):
        assert _fechas_del_plazo(plazo) == esperado

    def test_un_mes_invalido_no_revienta_el_informe(self):
        assert _fechas_del_plazo({"tipo": "fecha_anual", "vence": "99-99"}) == "99-99"

    @pytest.mark.parametrize("xs,esperado", [
        ([], ""), (["a"], "a"), (["a", "b"], "a y b"), (["a", "b", "c"], "a, b y c"),
    ])
    def test_la_lista_en_prosa_lleva_Y_final(self, xs, esperado):
        assert _lista_en_prosa(xs) == esperado

    def test_toda_periodicidad_del_repo_se_puede_decir_en_prosa(self):
        """Una periodicidad nueva sin traducción sale como «por una sola vez», que sería
        falso. El guard la obliga a declararse."""
        faltan = set()
        for eid in expedientes():
            for o in cargar_obligaciones(eid):
                if o.hito_de_medicion and o.periodicidad and o.periodicidad not in CADA_CUANTO:
                    faltan.add(o.periodicidad)
        assert not faltan, f"periodicidades sin traducción en CADA_CUANTO: {sorted(faltan)}"


def test_ninguna_ley_pierde_su_calendario_en_SILENCIO():
    """Si un expediente declara hitos, la sección TIENE que salir.

    Es el modo de fallo de este repositorio: la pieza se arma bien y no se cablea a la
    superficie, y nadie lo nota porque el documento igual se genera.
    """
    for eid in expedientes():
        hitos = [o for o in cargar_obligaciones(eid) if o.hito_de_medicion]
        s = construir(eid, None)["secciones"].get("cuando_manda_la_ley_medir")
        if hitos:
            assert s, f"«{eid}» declara {len(hitos)} hito(s) y el informe no los publica"
            assert str(hitos[0].articulo) in str(construir(eid, None)["tablas"])


class TestElCasoCERO:
    """«0 de ellas tienen una consecuencia… El resto no» es lo que sale de interpolar un
    contador en una frase escrita para el caso general. No concuerda, y entierra lo
    interesante: que la END no trae NINGÚN mecanismo de exigibilidad."""

    def test_la_END_lo_dice_como_HALLAZGO_y_no_como_conteo(self):
        s = construir("end_2030", None)["secciones"]["lo_que_ordena"]
        assert "Ninguna de ellas trae una consecuencia jurídica" in s
        assert "0 de ellas" not in s
        assert "El resto no" not in s

    def test_con_algunas_se_dice_cuántas_y_concuerda(self):
        s = construir("ley_167_21", None)["secciones"]["lo_que_ordena"]
        assert "2 de ellas tienen una consecuencia" in s
        assert "Las restantes no" in s
