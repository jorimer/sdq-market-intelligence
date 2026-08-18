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
    assert c.evidencia.endswith("Gaceta 10753.")
