"""La unidad de la pregunta es el INDICADOR, no la brecha del eje.

El agente general recorre brechas y propone ≤2 por brecha. El eje de leyes tiene UNA, así que
90 indicadores colapsaban en dos propuestas y el prompt sólo podía decir «amplíe la fuente».
La corrida real lo confirmó: dos propuestas, una para un organismo disuelto.
"""
import json

import pytest

from modules.law_intel.agente_fuentes import (MAX_POR_CORRIDA, _pregunta, _parsear, proponer,
                                              resumen, sin_fuente)
from modules.law_intel.registro import Indicador

E = "end_2030"


def ind(**kw):
    base = dict(id="1.8", eje=1, nombre="Tasa de homicidios", escala="numerica",
                base_anio=2008, base_valor=24.8, metas={"2025": 10.0, "2030": 4.0})
    return Indicador(**{**base, **kw})


class TestLaPregunta:
    def test_lleva_el_nombre_la_base_y_las_metas(self):
        q = _pregunta(ind(), "Ley 1-12")
        assert "Tasa de homicidios" in q and "24.8" in q and "2008" in q and "2025: 10.0" in q

    def test_pide_vacio_antes_que_una_aproximacion(self):
        """Una fuente parecida atada a un indicador legal produce un incumplimiento inventado."""
        q = _pregunta(ind(), "Ley 1-12")
        assert "arreglo vacío" in q and "aproximada" in q

    def test_declara_sin_linea_base_cuando_no_la_hay(self):
        assert "sin línea base declarada" in _pregunta(ind(base_valor=None), "Ley 1-12")


class TestLaReglaDeIndependencia:
    def test_el_sistema_prohibe_la_autoevaluacion_del_evaluado(self):
        """Es el hallazgo central del expediente y la razón por la que se rechazó la
        propuesta del MEPyD en la corrida real."""
        from modules.law_intel.agente_fuentes import _SISTEMA
        assert "autoevaluación no sirve" in _SISTEMA
        assert "SERIES" in _SISTEMA, "sí sirven las series que ese órgano publica"


class TestParseo:
    def test_tolera_fences(self):
        assert _parsear('```json\n[{"title":"ONE"}]\n```')[0]["title"] == "ONE"

    def test_arreglo_vacio_es_respuesta_valida(self):
        assert _parsear("[]") == []

    def test_json_roto_no_rompe(self):
        assert _parsear("no soy json") == []

    def test_descarta_elementos_sin_titulo(self):
        assert _parsear('[{"description":"x"},{"title":"  "}]') == []


class TestBarrido:
    def _resp(self, *_):
        return json.dumps([{"title": "ONE — Boletín", "description": "publica la serie"}])

    def test_no_pregunta_por_lo_que_ya_se_mide(self):
        ids = {i.id for i in sin_fuente(E)}
        assert not ({"2.4", "2.18", "2.19", "2.21"} & ids)

    def test_no_reabre_un_descartado(self):
        ids = {i.id for i in sin_fuente(E)}
        assert "3.26" not in ids and "3.9" not in ids

    def test_el_indicador_viaja_en_la_descripcion(self):
        """La sugerencia vive en el tablero general, donde el único campo de eje es
        `target_axis="law"`: sin esto nadie sabe a qué meta responde."""
        p = proponer(E, self._resp, max_indicadores=1).propuestas[0]
        assert p["description"].startswith("[Ley 1-12 · indicador ")
        assert p["indicador"] in p["description"]

    def test_el_tope_acota_las_LLAMADAS_no_las_propuestas(self):
        """Lo que cuesta es consultar, no obtener. Acotar la salida dejaba el gasto sin
        techo: con vacíos intercalados, un tope de 20 propuestas costaba 40 llamadas."""
        assert proponer(E, self._resp, max_indicadores=3).consultados == 3

        llamadas = {"n": 0}

        def alterna(s, u):
            llamadas["n"] += 1
            return "[]" if llamadas["n"] % 2 else self._resp()

        c = proponer(E, alterna, max_indicadores=6)
        assert c.consultados == 6 and llamadas["n"] == 6
        assert len(c.propuestas) == 3

    def test_no_repregunta_lo_ya_propuesto(self):
        primero = proponer(E, self._resp, max_indicadores=1).propuestas[0]["indicador"]
        segundo = proponer(E, self._resp, max_indicadores=1,
                           ya_propuestos={primero}).propuestas[0]["indicador"]
        assert segundo != primero

    def test_un_indicador_que_falla_no_aborta_el_barrido(self):
        estado = {"n": 0}

        def a_veces_rompe(s, u):
            estado["n"] += 1
            if estado["n"] == 1:
                raise RuntimeError("timeout")
            return self._resp()

        # El que falla YA contó como consultado: reintentarlo dentro de la misma corrida
        # sería un bucle contra un modelo caído.
        c = proponer(E, a_veces_rompe, max_indicadores=2)
        assert c.consultados == 2 and len(c.propuestas) == 1

    def test_vacio_del_modelo_no_es_error(self):
        """Que ninguna fuente publique esa magnitud con esa definición es un RESULTADO."""
        c = proponer(E, lambda s, u: "[]", max_indicadores=5)
        assert c.propuestas == [] and c.consultados == 5
        r = resumen(c)
        assert r["sin_propuesta"] == 5 and r["con_propuesta"] == 0
        assert "no una falla" in r["nota"]


def test_le_da_al_modelo_los_hechos_institucionales_que_no_conoce():
    """En la prueba real nombró tres veces al MEPyD, disuelto en julio de 2025. Sin
    corregirlo, el tablero se llena de propuestas a un organismo que no existe."""
    from modules.law_intel.agente_fuentes import _SISTEMA
    assert "45-25" in _SISTEMA and "DISUELTO" in _SISTEMA
    assert "Hacienda y Economía" in _SISTEMA


# ── La marca es el ancla de la idempotencia ───────────────────────────────────────────────
# El tablero de source_intel no tiene campo para un indicador: su único campo de eje es
# `target_axis`, que vale "law" para las 84. El indicador viaja en la descripción, y esa
# marca es lo único que permite a la segunda corrida saltar lo ya preguntado. Si el formato
# se desincroniza entre `marca` e `indicador_de`, nada falla: simplemente se vuelve a
# preguntar por los 84 y se paga dos veces.

def test_marca_e_indicador_de_son_inversas_en_TODOS_los_indicadores():
    from modules.law_intel.agente_fuentes import indicador_de, marca
    from modules.law_intel.registro import cargar
    exp = cargar("end_2030")
    assert exp.numerados, "el expediente quedó vacío; el test no probaría nada"
    for ind in exp.numerados:
        assert indicador_de(marca(exp.norma, ind)) == ind.id, ind.id


def test_la_marca_sobrevive_al_texto_del_modelo_pegado_detras():
    """En producción la marca es un PREFIJO: lo que sigue es prosa del modelo, con guiones
    y corchetes propios. El parser debe anclarse al principio y no confundirse."""
    from modules.law_intel.agente_fuentes import indicador_de
    d = ("[Ley 1-12 · indicador 2.19 — Tasa de analfabetismo] La ONE publica la tasa de "
         "alfabetización [ENHOGAR] — su complemento es este indicador.")
    assert indicador_de(d) == "2.19"


def test_una_descripcion_sin_marca_no_inventa_indicador():
    from modules.law_intel.agente_fuentes import indicador_de
    assert indicador_de("Propuesta manual de un humano, sin marca") is None
    assert indicador_de("") is None


def test_el_indicador_de_la_propuesta_coincide_con_su_marca():
    """La clave `indicador` y la marca de la descripción no pueden divergir: la primera es
    lo que ve el código, la segunda lo único que persiste en el tablero."""
    from modules.law_intel.agente_fuentes import indicador_de, proponer
    props = proponer("end_2030",
                     lambda s, u: '[{"title": "ONE — X", "description": "mide X"}]',
                     max_indicadores=6).propuestas
    assert props
    for p in props:
        assert indicador_de(p["description"]) == p["indicador"]


def test_el_barrido_contabiliza_su_gasto():
    """Un barrido son 84 llamadas. Si no cuentan contra LLM_DAILY_BUDGET_USD, el techo
    diario no puede cortarlo."""
    import ast
    import inspect

    from modules.law_intel import agente_fuentes
    arbol = ast.parse(inspect.getsource(agente_fuentes))
    llamadas = {n.func.id for n in ast.walk(arbol)
                if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)}
    assert "account" in llamadas


# ── El cableado al tablero ────────────────────────────────────────────────────────────────

@pytest.fixture()
def tablero():
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    from sqlalchemy.pool import StaticPool

    from shared.auth.models import User
    from shared.database.base import Base
    from shared.source_intel.models import SourceSuggestion

    eng = create_engine("sqlite://", connect_args={"check_same_thread": False},
                        poolclass=StaticPool)
    Base.metadata.create_all(eng, tables=[User.__table__, SourceSuggestion.__table__])
    s = sessionmaker(bind=eng)()
    try:
        yield s
    finally:
        s.close()


def _responde_siempre(_s, _u):
    return '[{"title": "ONE — Serie X", "description": "publica X cada año"}]'


def test_la_segunda_corrida_no_vuelve_a_preguntar_por_lo_ya_propuesto(tablero):
    """La idempotencia es lo que separa un barrido de US$0,76 de pagar dos veces por lo
    mismo. Y no vive en el código sino en el tablero: la marca es lo único que persiste."""
    from modules.law_intel.agente_fuentes import barrer

    preguntados = []

    def espia(s, u):
        preguntados.append(u)
        return _responde_siempre(s, u)

    r1 = barrer(tablero, "end_2030", max_indicadores=5, preguntar=espia)
    assert r1["creadas"] == 5 and r1["ya_propuestos"] == 0
    n1 = len(preguntados)

    r2 = barrer(tablero, "end_2030", max_indicadores=5, preguntar=espia)
    assert r2["ya_propuestos"] == 5, "la segunda corrida no leyó las propuestas abiertas"
    # Preguntó por CINCO indicadores distintos, no por los mismos cinco.
    assert len(preguntados) == n1 + 5
    assert len(set(preguntados)) == len(preguntados)


def test_el_barrido_declara_lo_que_dejo_afuera(tablero):
    """Truncar en silencio haría leer «se recorrió todo» donde se recorrió una parte."""
    from modules.law_intel.agente_fuentes import barrer, sin_fuente

    faltan = len(sin_fuente("end_2030"))
    r = barrer(tablero, "end_2030", max_indicadores=3, preguntar=_responde_siempre)
    assert r["capado"] is True
    assert r["restantes"] == faltan - 3


def test_la_propuesta_llega_al_tablero_anclada_al_eje_y_al_gate(tablero):
    from modules.law_intel.agente_fuentes import barrer, indicador_de
    from shared.source_intel.models import SourceSuggestion

    barrer(tablero, "end_2030", max_indicadores=2, preguntar=_responde_siempre)
    filas = tablero.query(SourceSuggestion).all()
    assert len(filas) == 2
    for f in filas:
        assert f.target_axis == "law" and f.target_gate == "g1"
        assert indicador_de(f.description), "sin marca, la corrida siguiente re-pregunta"


def test_un_indicador_sin_propuesta_no_crea_fila_ni_bloquea_el_resto(tablero):
    """Vacío es la respuesta correcta cuando ninguna fuente mide esa magnitud. No debe
    dejar rastro en el tablero: una fila vacía se leería como «ya lo preguntamos»."""
    from modules.law_intel.agente_fuentes import barrer

    llamadas = {"n": 0}

    def a_veces(s, u):
        llamadas["n"] += 1
        return "[]" if llamadas["n"] % 2 else _responde_siempre(s, u)

    r = barrer(tablero, "end_2030", max_indicadores=4, preguntar=a_veces)
    assert r["creadas"] == 2 and r["sin_propuesta"] == 2
    assert llamadas["n"] == 4, "un vacío cortó el barrido en vez de seguir"


def test_una_llamada_que_FALLA_no_se_cuenta_como_falta_de_fuente():
    """«Ninguna fuente publica esto» y «no pudimos preguntar» son cosas distintas. El módulo
    entero existe para no confundirlas; confundirlas acá convertiría una caída del proveedor
    en un hallazgo sobre el Estado dominicano."""
    from modules.law_intel.agente_fuentes import proponer, resumen

    def rompe(_s, _u):
        raise RuntimeError("overloaded_error")

    r = resumen(proponer("end_2030", rompe, max_indicadores=3))
    assert r["fallidos"] == 3
    assert r["respondieron"] == 0
    assert r["sin_propuesta"] == 0, "un fallo se estaba contando como ausencia de fuente"
    assert all("overloaded" in m for m in r["motivos_de_falla"].values())


def test_las_tandas_avanzan_aunque_el_modelo_responda_vacio(tablero):
    """La idempotencia por tablero solo cubre lo que dejó rastro. Un vacío no crea fila, así
    que sin `omitir` cada tanda re-consulta los mismos vacíos desde el principio y el barrido
    de 83 indicadores no termina nunca."""
    from modules.law_intel.agente_fuentes import barrer

    r1 = barrer(tablero, "end_2030", max_indicadores=3, preguntar=lambda s, u: "[]")
    assert r1["creadas"] == 0 and len(r1["consultados_ids"]) == 3

    r2 = barrer(tablero, "end_2030", max_indicadores=3, preguntar=lambda s, u: "[]",
                omitir=set(r1["consultados_ids"]))
    assert not set(r2["consultados_ids"]) & set(r1["consultados_ids"]), \
        "la segunda tanda repitió indicadores: el barrido no avanza"
