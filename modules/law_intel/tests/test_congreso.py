"""Un registro que no declara su cobertura no puede concluir una ausencia sin control positivo.

Es la diferencia con la verificación normativa, y es la razón de existir de este módulo. Allá
el emisor declara `vacio_es_concluyente` y ese campo es lo único que autoriza a publicar «no se
dictó». Acá no hay tal campo: el registro devuelve una lista y punto, así que el motor tiene
que probarse a sí mismo que la consulta funciona antes de leer un vacío como un hecho.

El caso real que lo motivó: la búsqueda por palabra clave del propio registro devuelve CERO
para «bicameral» mientras el listado por tipo devuelve cinco comisiones bicamerales.
"""
import pytest

from modules.law_intel import congreso as C

OID = "art-51-comision-bicameral"
OID50 = "art-50-informe-de-vinculacion"


def _doc(titulo):
    return {"descripcion": titulo}


def _listado(permanentes, especiales):
    def fn(tipo_id):
        return {C.TIPO_BICAMERAL_PERMANENTE: permanentes,
                C.TIPO_BICAMERAL_ESPECIAL: especiales}[tipo_id]
    return fn


class TestElControlPositivo:
    """La regla central: una consulta que no probó que puede encontrar algo no encuentra nada."""

    def test_si_el_control_cae_el_veredicto_es_no_verificable(self):
        c = C.comprobar_comision_bicameral(OID, _listado([], []))
        assert c.veredicto == "no_verificable"
        assert "control positivo" in c.evidencia
        assert not c.acusa

    def test_el_control_viaja_en_el_alcance_aunque_pase(self):
        """Que haya pasado es un dato del informe, no un detalle de implementación."""
        c = C.comprobar_comision_bicameral(OID, _listado([], [{"comision": "x"}]))
        assert c.alcance["control_positivo"] == {
            "consulta": "comisiones bicamerales especiales", "resultados": 1, "vale": True}

    def test_ningun_vacio_de_este_registro_es_concluyente(self):
        """No hay ninguna rama que pueda afirmar que un acto no ocurrió."""
        c = C.comprobar_comision_bicameral(OID, _listado([], [{"comision": "x"}]))
        assert c.alcance["vacio_es_concluyente"] is False
        assert c.veredicto == "sin_registro_publico"
        assert "No se afirma incumplimiento" in c.evidencia


class TestLaComisionBicameral:
    def test_la_actuacion_documentada_impide_la_afirmacion_negativa(self):
        """El defecto que este módulo existe para no repetir.

        Mirar solo el catálogo de permanentes da cero y tienta a publicar «no consta comisión
        bicameral». El expediente presupuestario trae los informes de una, así que esa frase
        se refuta con el propio archivo del obligado.
        """
        c = C.comprobar_comision_bicameral(
            OID, _listado([], [{"comision": "x"}]),
            [_doc("INFORME COMISIÓN BICAMERAL"), _doc("PROYECTO DEPOSITADO")])
        assert c.veredicto == "parcial"
        assert "SÍ examina el Presupuesto" in c.evidencia
        assert "PERMANENTE" in c.evidencia

    def test_lo_que_acusa_lleva_su_evidencia(self):
        c = C.comprobar_comision_bicameral(
            OID, _listado([], [{"comision": "x"}]), [_doc("ACUSE COMISIÓN BICAMERAL")])
        assert c.acusa
        assert c.hallazgos, "una acusación sin los documentos que la sostienen no sale"

    def test_una_permanente_registrada_da_cumplida(self):
        c = C.comprobar_comision_bicameral(
            OID, _listado([{"comision": "Bicameral de Planificación y Presupuesto"}],
                          [{"comision": "x"}]))
        assert c.veredicto == "cumplida"

    def test_el_periodo_servido_se_lee_de_los_registros(self):
        """Computado, no supuesto: el registro no dice qué período sirve."""
        c = C.comprobar_comision_bicameral(
            OID, _listado([], [{"comision": "x", "fechaDesignacion": "2025-05-27T00:00:00"},
                               {"comision": "y", "fechaDesignacion": "2026-06-15T00:00:00"}]))
        assert c.alcance["periodo_legislativo_servido"] == "2025-2026"

    def test_una_caida_del_registro_no_es_una_ausencia(self):
        def cae(_):
            raise RuntimeError("timeout")
        c = C.comprobar_comision_bicameral(OID, cae)
        assert c.veredicto == "no_verificable"


class TestElInformeDeVinculacion:
    def _docs(self, mapa):
        return lambda iid: mapa[iid]

    def test_sin_presupuestos_no_hay_ausencia_que_leer(self):
        c = C.comprobar_informe_de_vinculacion(OID50, [], self._docs({}))
        assert c.veredicto == "no_verificable"
        assert c.alcance["control_positivo"]["vale"] is False

    def test_el_titulo_no_alcanza_para_dar_por_cumplido(self):
        """El deber depende del CONTENIDO y el contenido no se puede leer.

        `solo_registral` es la traducción de la distinción que el emisor de la base normativa
        llama `registral` contra `texto`: sabemos que el documento existe, no qué dice.
        """
        pge = [{"id": 1, "numero": "A", "fechaDeposito": "2025-09-26"}]
        c = C.comprobar_informe_de_vinculacion(
            OID50, pge, self._docs({1: [_doc("INFORME DE VINCULACIÓN CON LA END 2030")]}))
        assert c.veredicto == "solo_registral"
        assert c.veredicto != "cumplida"
        assert "no se juzga" in c.evidencia

    def test_sin_seña_no_afirma_incumplimiento_y_dice_los_dos_motivos(self):
        pge = [{"id": 1, "numero": "A", "fechaDeposito": "2025-09-26"}]
        c = C.comprobar_informe_de_vinculacion(
            OID50, pge, self._docs({1: [_doc("INFORME EXPLICATIVO Y MARCO DE GASTO")]}))
        assert c.veredicto == "sin_registro_publico"
        assert "NO se afirma incumplimiento" in c.evidencia
        assert "período legislativo vigente" in c.evidencia

    def test_una_caida_a_media_lectura_no_se_degrada(self):
        pge = [{"id": 1, "numero": "A", "fechaDeposito": "2025-09-26"}]
        def cae(_):
            raise RuntimeError("500")
        c = C.comprobar_informe_de_vinculacion(OID50, pge, cae)
        assert c.veredicto == "no_verificable"


class TestElDenominadorDelArticulo50:
    def test_solo_cuentan_los_proyectos_del_ejecutivo(self):
        """El registro devuelve también resoluciones que piden incluir obras en el Presupuesto.

        Contarlas multiplicaría por diez el denominador y volvería trivial cualquier
        proporción de cumplimiento.
        """
        crudas = [
            {"tipo": "Proyecto de Ley", "origen": "Poder Ejecutivo",
             "descripcion": "Proyecto de ley de presupuesto general del Estado para el año 2026."},
            {"tipo": "Resolución Interna", "origen": "Cámara de Diputados",
             "descripcion": "…incluir en el Presupuesto General del Estado la construcción…"},
            {"tipo": "Proyecto de Ley", "origen": "Poder Ejecutivo",
             "descripcion": "Proyecto de ley que modifica la Ley núm. 99-25 de Presupuesto General."},
        ]
        assert len(C.presupuestos_anuales(crudas)) == 1


@pytest.mark.parametrize("veredicto", sorted(C.VEREDICTOS))
def test_ningun_veredicto_de_este_modulo_afirma_incumplimiento(veredicto):
    """`incumplida` NO está en el vocabulario, y es deliberado.

    Ninguna consulta a este registro puede sostenerla: no declara su cobertura y sirve un solo
    período legislativo. Dejar la palabra disponible sería dejar cargada el arma para el
    próximo que agregue una rama.
    """
    assert veredicto != "incumplida"


def test_ESTRUCTURAL_ningun_veredicto_se_inventa_fuera_del_vocabulario():
    """Se lee el CÓDIGO: cada `Comprobacion(...)` usa un veredicto declarado en `VEREDICTOS`.

    Es el defecto que se repite cada vez que alguien agrega una rama: el diccionario queda
    como documentación y el motor devuelve una palabra que ningún consumidor sabe interpretar.
    La lección escrita no alcanzó en este repo —por eso la regla la comprueba `ast` y no una
    revisión.
    """
    import ast
    import inspect

    from modules.law_intel import congreso

    arbol = ast.parse(inspect.getsource(congreso))
    usados = set()
    for nodo in ast.walk(arbol):
        if (isinstance(nodo, ast.Call) and isinstance(nodo.func, ast.Name)
                and nodo.func.id == "Comprobacion" and len(nodo.args) >= 2
                and isinstance(nodo.args[1], ast.Constant)):
            usados.add(nodo.args[1].value)
    assert usados, "el barrido no encontró ninguna Comprobacion: dejó de proteger algo"
    assert usados <= set(C.VEREDICTOS), f"veredictos fuera del vocabulario: {usados - set(C.VEREDICTOS)}"


@pytest.mark.parametrize("comprobar", ["comision", "informe"])
def test_el_alcance_nunca_queda_en_None_cuando_hubo_registros(comprobar):
    """«No sé de qué período es» y «cubre todo» son cosas distintas.

    La evidencia de las dos comprobaciones AFIRMA que el registro sirve un solo período
    legislativo. Servir esa frase con el campo vacío al lado es la misma trampa que
    `stale=null` en la frescura de validación: el hueco se lee como que no hay límite.

    Pasó de verdad: el artículo 50 salía con `periodo_legislativo_servido: None` porque una
    iniciativa se DEPOSITA y una comisión se DESIGNA, y solo se leía la segunda fecha.
    """
    if comprobar == "comision":
        c = C.comprobar_comision_bicameral(
            OID, _listado([], [{"comision": "x", "fechaDesignacion": "2025-05-27T00:00:00"}]))
    else:
        c = C.comprobar_informe_de_vinculacion(
            OID50, [{"id": 1, "numero": "A", "fechaDeposito": "2025-09-26"}],
            lambda _: [_doc("PROYECTO DEPOSITADO")])
    assert c.alcance["periodo_legislativo_servido"] is not None
