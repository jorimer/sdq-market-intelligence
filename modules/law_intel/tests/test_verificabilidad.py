"""El emisor no es el productor, y esa distinción es la sección entera.

Lo que estos tests protegen no es una cifra: es que la cifra siga siendo COMPUTADA. La
proporción de evidencia independiente es la única del informe que habla del informe mismo,
así que es la que más tienta a redondear hacia arriba — y el redondeo tiene una forma
concreta: contar «lo publica el Banco Mundial» como medición de tercero.
"""
import pytest
from dataclasses import fields

from modules.law_intel.bindings import Binding, ExpedienteInvalido, _validar
from modules.law_intel.obligaciones import Obligacion
from modules.law_intel.registro import Expediente, Indicador
from modules.law_intel.verificabilidad import (INDEPENDIENTES, ORIGENES, ORIGENES_DE_INDICADOR,
                                               Evidencia, _origen_de_obligacion,
                                               evidencia_de_indicadores,
                                               evidencia_de_obligaciones, publicable)

EXPEDIENTE = "end_2030"


@pytest.fixture(scope="module")
def pub():
    return publicable(EXPEDIENTE)


def _exp_falso():
    ind = Indicador(id="1.8", eje=1, nombre="x", escala="numerica", base_valor=24.8,
                    metas={"2015": 20.0, "2030": 4.0})
    return Expediente(id="t", titulo="t", norma="t",
                      meta={"fuentes_admitidas": [{"id": "one", "nombre": "ONE",
                                                   "del_evaluado": True}]},
                      indicadores=[ind])


def _binding(**kw):
    base = dict(indicador="1.8", serie="s", fuente="one", mejor="menor", estado="verificado",
                periodo_verificado="2024", origen="declarado_por_el_evaluado", productor="ONE")
    return Binding(**{**base, **kw})


class TestElGuardDeOrigen:
    """Un binding sin cadena de evidencia declarada no entra: el hueco lo llenaría el lector."""

    def test_sin_origen_no_carga(self):
        with pytest.raises(ExpedienteInvalido, match="sin `origen`"):
            _validar(_exp_falso(), [_binding(origen=None)])

    def test_sin_productor_no_carga(self):
        with pytest.raises(ExpedienteInvalido, match="QUIÉN produce"):
            _validar(_exp_falso(), [_binding(productor=None)])

    def test_un_origen_inventado_no_carga(self):
        with pytest.raises(ExpedienteInvalido, match="fuera del conjunto"):
            _validar(_exp_falso(), [_binding(origen="parece_confiable")])

    def test_un_indicador_no_puede_declararse_acto_registral(self):
        """La etiqueta más independiente del conjunto, sobre la evidencia más débil.

        Un indicador se mide; no se dicta. Sin este corte, cualquier serie podría vestirse de
        acto en la Gaceta y entrar al numerador de independencia.
        """
        assert "acto_en_registro_publico" in ORIGENES
        assert "acto_en_registro_publico" not in ORIGENES_DE_INDICADOR
        with pytest.raises(ExpedienteInvalido, match="fuera del conjunto"):
            _validar(_exp_falso(), [_binding(origen="acto_en_registro_publico")])

    def test_el_descartado_tambien_declara_origen(self):
        """Porque la sección cuenta lo que la ley PERDIÓ, y eso vive en los descartes."""
        with pytest.raises(ExpedienteInvalido, match="sin `origen`"):
            _validar(_exp_falso(), [_binding(estado="descartado", motivo_descarte="x",
                                             origen=None)])


class TestElEmisorNoEsElProductor:
    """El hallazgo central: un sello internacional no es una medición internacional."""

    def test_emisor_ajeno_con_dato_del_evaluado_no_cuenta_como_independiente(self):
        e = Evidencia(sujeto="3.13", nombre="x", clase="indicador",
                      origen="declarado_por_el_evaluado", productor="INDOTEL vía UIT",
                      emisor="wdi", emisor_del_evaluado=False)
        assert not e.independiente
        assert e.emisor_externo_sin_medicion_propia

    def test_una_estimacion_de_tercero_tampoco_es_independiente(self):
        """La frontera está deliberadamente alta: el método es ajeno, el insumo no.

        Una estimación modelada sobre las rondas ENDESA hereda lo que el evaluado reportó.
        Contarla como independiente sería subir la cifra que el propio informe usa para
        defender su independencia.
        """
        assert "estimacion_de_tercero_sobre_dato_del_evaluado" not in INDEPENDIENTES

    def test_en_el_expediente_real_hay_emisores_ajenos_que_no_miden(self, pub):
        d = pub["emisor_no_es_productor"]
        assert d["medidos_con_emisor_ajeno_al_evaluado"] >= \
            d["de_esos_cuantos_miden_con_dato_del_evaluado"]
        # El contraste tiene que existir de verdad, o el test pasa sin proteger nada.
        assert d["de_esos_cuantos_miden_con_dato_del_evaluado"] > 0
        assert len(d["ids"]) == d["de_esos_cuantos_miden_con_dato_del_evaluado"]


class TestLoQueLaLeyPerdio:
    def test_los_perdidos_no_estan_medidos(self, pub):
        medidos = {e["sujeto"] for e in pub["cadena_por_sujeto"] if e["clase"] == "indicador"}
        d = pub["instrumentos_de_tercero_que_la_ley_eligio"]
        assert not (set(d["ids_perdidos"]) & medidos)
        assert d["todavia_medibles"] + d["perdidos"] == d["indicadores_que_se_apoyaban_en_uno"]

    def test_la_ley_si_previo_verificacion_de_tercero(self, pub):
        """El hallazgo se sostiene en que hubo instrumentos, no en que falten fuentes."""
        assert pub["instrumentos_de_tercero_que_la_ley_eligio"]["perdidos"] > 0


class TestObligaciones:
    def test_la_que_se_comprueba_contra_la_gaceta_es_independiente(self):
        o = Obligacion(id="x", articulo=54, deber="dictar el reglamento",
                       deudor={"tipo": "organo"}, estado="cumplida_tarde", evidencia="ev",
                       verificacion_normativa={"cita_a": "ley:1-12", "tipo": "decreto"})
        assert _origen_de_obligacion(o) == "acto_en_registro_publico"
        assert "acto_en_registro_publico" in INDEPENDIENTES

    def test_la_que_solo_se_comprueba_preguntando_al_obligado_no_lo_es(self):
        o = Obligacion(id="x", articulo=41, deber="publicar un informe",
                       deudor={"tipo": "organo"}, estado="cumplida",
                       sin_consulta_normativa="el deber produce un informe, no una norma")
        assert _origen_de_obligacion(o) == "declarado_por_el_evaluado"

    def test_lo_que_no_tiene_nada_que_verificar_queda_fuera_del_denominador(self):
        """Contarla mejoraría la proporción sin que nada sea más verificable."""
        o = Obligacion(id="x", articulo=36, deber="concertar un pacto",
                       deudor={"tipo": "indeterminado"}, estado="no_exigible")
        assert _origen_de_obligacion(o) is None

    def test_el_expediente_real_no_las_cuenta(self, pub):
        d = pub["obligaciones_verificables"]
        assert d["contra_registro_publico"] + d["solo_por_declaracion_del_obligado"] == \
            d["total_con_algo_que_verificar"]
        ids = {e["sujeto"] for e in pub["cadena_por_sujeto"] if e["clase"] == "obligacion"}
        assert d["total_con_algo_que_verificar"] == len(ids)


class TestElReparto:
    def test_lista_los_ceros(self, pub):
        """Un origen ausente se lee como «no aplica» y acá significa «ninguna evidencia lo
        alcanza», que es justamente el dato."""
        reparto = pub["indicadores_medidos"]["reparto_por_origen_sobre_los_medidos"]
        assert set(reparto) == set(ORIGENES)

    def test_el_reparto_suma_los_medidos(self, pub):
        d = pub["indicadores_medidos"]
        assert sum(d["reparto_por_origen_sobre_los_medidos"].values()) == d["total_medidos"]

    def test_los_independientes_son_un_subconjunto_de_los_medidos(self, pub):
        d = pub["indicadores_medidos"]
        assert d["con_medicion_independiente_del_evaluado"] <= d["total_medidos"]
        assert len(d["ids_con_medicion_independiente"]) == \
            d["con_medicion_independiente_del_evaluado"]

    def test_solo_cuenta_los_verificados(self):
        """Un binding propuesto es una hipótesis; sumarlo diría que se mide lo que no."""
        medidos = evidencia_de_indicadores(EXPEDIENTE, solo_medidos=True)
        todos = evidencia_de_indicadores(EXPEDIENTE, solo_medidos=False)
        assert len(medidos) < len(todos)


def test_REGLA_todo_campo_de_una_evidencia_LLEGA_o_se_declara_interno():
    """La lección que se repitió tres veces en un día: un campo que el serializador no expone
    es indistinguible de uno que no existe.

    Se compara la CLASE entera contra lo que la sección publica, no una lista escrita a mano
    — una lista a mano envejece con el mismo silencio que el defecto que intenta atajar.
    """
    INTERNOS = frozenset()   # nada interno: la cadena de evidencia se publica entera
    servidos = set(publicable(EXPEDIENTE)["cadena_por_sujeto"][0])
    # `independiente_del_evaluado` es la propiedad computada de `origen`; se sirve con otro
    # nombre porque en el informe se lee como afirmación, no como campo.
    alias = {"independiente": "independiente_del_evaluado"}
    faltan = [f.name for f in fields(Evidencia)
              if alias.get(f.name, f.name) not in servidos and f.name not in INTERNOS]
    assert not faltan, f"campos declarados que ningún consumidor ve: {faltan}"


def test_el_expediente_real_declara_la_cadena_de_todos_sus_bindings():
    """Sin barrido vacío: si no hubiera bindings, este test pasaría sin comprobar nada."""
    evs = evidencia_de_indicadores(EXPEDIENTE, solo_medidos=False)
    assert len(evs) > 20
    for e in evs:
        assert e.origen in ORIGENES_DE_INDICADOR, e.sujeto
        assert e.productor.strip(), e.sujeto
        assert e.emisor_del_evaluado is not None, e.sujeto


def test_cada_obligacion_del_expediente_dice_como_se_comprueba():
    evs = evidencia_de_obligaciones(EXPEDIENTE)
    assert evs
    for e in evs:
        assert e.origen in ORIGENES
        assert e.productor.strip(), e.sujeto
