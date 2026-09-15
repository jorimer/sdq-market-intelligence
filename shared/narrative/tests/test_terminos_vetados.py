"""Un término que el contexto declara prohibido no se publica: se regenera, y si persiste se
quita la oración. Producción, 2026-09-15: el IAI escribió «percentil» sobre un puesto."""
import asyncio

from shared.narrative import claude_engine
from shared.narrative.claude_engine import _MAX_REINTENTOS_GUARD, NarrativeEngine
from shared.narrative.terminos_vetados import CLAVE, quitar_oraciones_con, terminos_en

_VETO = {CLAVE: {"percentil": "lo servido es un puesto"}}


class _Msg:
    def __init__(self, text):
        self.content = [type("C", (), {"text": text})()]
        self.usage = type("U", (), {"input_tokens": 10, "output_tokens": 20})()


def _motor(monkeypatch, textos):
    eng, llamadas, cola = NarrativeEngine(), [], list(textos)

    class _Cliente:
        class messages:
            @staticmethod
            def create(**kw):
                if "verificador" in (kw.get("system") or ""):
                    return _Msg('{"unsupported": []}')
                llamadas.append(kw)
                return _Msg(cola.pop(0) if len(cola) > 1 else cola[0])

    monkeypatch.setattr(eng, "_get_client", lambda: _Cliente())
    monkeypatch.setattr(claude_engine.settings, "ANTHROPIC_MODEL", "test-model", raising=False)
    monkeypatch.setattr(claude_engine.settings, "ANTHROPIC_GUARD_MODEL", "test-judge", raising=False)
    return eng, llamadas


def _generar(eng, contexto):
    return asyncio.run(eng.generate(contexto, template="sector_outlook", axis="sector_intel",
                                    audience="inversionista"))


def test_se_detecta_como_palabra_y_con_sus_flexiones():
    assert terminos_en(_VETO, "Cae en el Percentil inferior.") == ["percentil"]
    assert terminos_en(_VETO, "Los percentiles del panel.") == ["percentil"]
    assert terminos_en(_VETO, "Ocupa el puesto 7 de 17.") == []
    assert terminos_en({}, "el percentil 90") == [], "sin declaración no se vigila nada"
    # El borde IZQUIERDO importa: un término dentro de otra palabra no es el término.
    assert terminos_en({CLAVE: {"tasa": "x"}}, "la sobretasa del crédito") == []
    assert terminos_en({CLAVE: {"tasa": "x"}}, "la tasa del crédito") == ["tasa"]


def test_se_detecta_sin_tilde_y_con_espacios_de_mas():
    """El modelo a veces pierde una tilde o duplica un espacio; el veto no puede depender de eso.
    Un salto de línea NO une: quitar trabaja por línea y no podría sacar lo que detectó."""
    veto = {CLAVE: {"umbral mínimo": "x"}}
    assert terminos_en(veto, "sobre el umbral minimo del modelo") == ["umbral mínimo"]
    assert terminos_en(veto, "sobre el Umbral  Mínimos del modelo") == ["umbral mínimo"]
    assert terminos_en({CLAVE: {"minimo": "x"}}, "el mínimo") == ["minimo"]
    assert terminos_en(veto, "el umbral\nmínimo") == []


def test_el_aviso_trae_el_MOTIVO_de_cada_termino(monkeypatch):
    """El motivo es la instrucción de reescritura: sin él, el aviso de un eje le dice al modelo
    lo que corresponde a otro («cita el puesto» no le sirve al año de un banco)."""
    eng, llamadas = _motor(monkeypatch, ["Cae en el percentil inferior.",
                                         "Ocupa el puesto 7 de 17."])
    _generar(eng, {"x": 1, **_VETO})
    aviso = llamadas[1]["messages"][0]["content"].partition("CORRECCIÓN OBLIGATORIA — TÉRMINOS")[2]
    assert "«percentil»" in aviso and "lo servido es un puesto" in aviso


def test_con_el_termino_se_REGENERA_con_el_aviso(monkeypatch):
    eng, llamadas = _motor(monkeypatch, ["Cae en el percentil inferior.",
                                         "Ocupa el puesto 7 de 17."])
    res = _generar(eng, {"x": 1, **_VETO})
    assert len(llamadas) == 2
    assert "TÉRMINOS" in llamadas[1]["messages"][0]["content"]
    assert res.text == "Ocupa el puesto 7 de 17."


def test_si_PERSISTE_se_quita_la_oracion_y_se_conserva_el_resto(monkeypatch):
    eng, llamadas = _motor(monkeypatch, [
        "El sector lidera en negocios. Cae en el percentil inferior del panel. Cierra estable."])
    res = _generar(eng, {"x": 1, **_VETO})
    assert len(llamadas) == 1 + _MAX_REINTENTOS_GUARD
    assert "percentil" not in res.text.lower()
    assert res.text == "El sector lidera en negocios. Cierra estable."


def test_sin_la_declaracion_el_texto_NO_se_toca(monkeypatch):
    eng, llamadas = _motor(monkeypatch, ["El indicador WGI está en el percentil 42."])
    res = _generar(eng, {"x": 1})
    assert len(llamadas) == 1 and "percentil" in res.text


def test_quitar_conserva_encabezados_y_lineas_limpias():
    texto = "## Posición\nCae en el percentil 25. Ocupa el puesto 7.\n\nOtra línea."
    nuevo, quitadas = quitar_oraciones_con(texto, ["percentil"])
    assert nuevo == "## Posición\nOcupa el puesto 7.\n\nOtra línea."
    assert quitadas == ["Cae en el percentil 25."]


def test_el_IAI_y_el_IDM_declaran_el_veto_en_su_contexto():
    from modules.sector_intel.ai_context import sector_ai_context
    from modules.social_dev.ai_context import social_ai_context
    assert "percentil" in sector_ai_context({"iai_breakdown": {}})[CLAVE]
    assert "percentil" in social_ai_context("el_valle", {"breakdown": {}})[CLAVE]
