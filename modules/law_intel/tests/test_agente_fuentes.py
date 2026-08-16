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
        p = proponer(E, self._resp, max_indicadores=1)[0]
        assert p["description"].startswith("[Ley 1-12 · indicador ")
        assert p["indicador"] in p["description"]

    def test_respeta_el_tope(self):
        assert len(proponer(E, self._resp, max_indicadores=3)) == 3

    def test_no_repregunta_lo_ya_propuesto(self):
        primero = proponer(E, self._resp, max_indicadores=1)[0]["indicador"]
        segundo = proponer(E, self._resp, max_indicadores=1,
                           ya_propuestos={primero})[0]["indicador"]
        assert segundo != primero

    def test_un_indicador_que_falla_no_aborta_el_barrido(self):
        estado = {"n": 0}

        def a_veces_rompe(s, u):
            estado["n"] += 1
            if estado["n"] == 1:
                raise RuntimeError("timeout")
            return self._resp()

        assert len(proponer(E, a_veces_rompe, max_indicadores=2)) == 2

    def test_vacio_del_modelo_no_es_error(self):
        """Que ninguna fuente publique esa magnitud con esa definición es un RESULTADO."""
        props = proponer(E, lambda s, u: "[]", max_indicadores=5)
        assert props == []
        r = resumen(props, len(sin_fuente(E)))
        assert r["sin_propuesta"] == min(len(sin_fuente(E)), MAX_POR_CORRIDA)
        assert "no una falla" in r["nota"]


def test_le_da_al_modelo_los_hechos_institucionales_que_no_conoce():
    """En la prueba real nombró tres veces al MEPyD, disuelto en julio de 2025. Sin
    corregirlo, el tablero se llena de propuestas a un organismo que no existe."""
    from modules.law_intel.agente_fuentes import _SISTEMA
    assert "45-25" in _SISTEMA and "DISUELTO" in _SISTEMA
    assert "Hacienda y Economía" in _SISTEMA
