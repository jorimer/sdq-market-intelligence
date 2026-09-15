"""Una LECTURA sin cifras: el contexto la declara y el lazo del motor la hace cumplir.

Cinco regeneraciones del Deep Dive 2025 de Banco Múltiple Santa Cruz (2026-09-15) sacaron,
cada una, un error distinto en una frase con número: la última escribió «63.49, apenas por
encima de donde empezó el año (64.15)». Cada guard cazaba una FORMA conocida, y la siguiente
vuelta traía otra. La cura no es otro guard de forma: las cifras y sus relaciones las escribe
el código, y el modelo escribe solo la interpretación. Este mecanismo es la mitad que la hace
cumplir: si el texto trae un dígito, se repara; si insiste, se quita la oración.
"""
from shared.narrative.lectura_sin_cifras import CLAVE, cifras_en, quitar_oraciones_con_cifras


def test_sin_la_clave_no_se_juzga_nada():
    assert cifras_en({}, "El score cerró en 63.49.") == []
    assert cifras_en({CLAVE: False}, "El score cerró en 63.49.") == []


def test_con_la_clave_todo_digito_es_una_cifra():
    ctx = {CLAVE: True}
    assert cifras_en(ctx, "cerró en 63.49, por encima de 64.15") == ["63.49", "64.15"]
    assert cifras_en(ctx, "el 52,6 % del movimiento") == ["52,6"]
    assert cifras_en(ctx, "en 2025 y en el T2") == ["2025", "T2"]
    assert cifras_en(ctx, "El segundo trimestre fue atípico frente a su historia.") == []


def test_se_quita_solo_la_oracion_con_cifra():
    texto = ("## Lectura 2025\n"
             "El segundo trimestre rompió el año. Cerró en 63.49, apenas por encima de 64.15. "
             "La calidad de activos se deterioró.\n\n"
             "- La liquidez sostuvo.")
    limpio, quitadas = quitar_oraciones_con_cifras(texto)
    assert "63.49" not in limpio and "2025" not in limpio
    assert "El segundo trimestre rompió el año." in limpio
    assert "La calidad de activos se deterioró." in limpio
    assert "- La liquidez sostuvo." in limpio
    assert len(quitadas) == 2


# ── Por el MOTOR real: el lazo repara y, si insiste, quita ────────────────────

class _Msg:
    def __init__(self, text):
        self.content = [type("C", (), {"text": text})()]
        self.usage = type("U", (), {"input_tokens": 10, "output_tokens": 20})()


def _generar(monkeypatch, textos, contexto):
    import asyncio

    from shared.narrative import claude_engine

    eng, llamadas, cola = claude_engine.narrative_engine, [], list(textos)

    class _Cliente:
        class messages:
            @staticmethod
            def create(**kw):
                if "verificador" in (kw.get("system") or ""):
                    return _Msg('{"unsupported": []}')
                llamadas.append(kw["messages"][0]["content"])
                return _Msg(cola.pop(0) if len(cola) > 1 else cola[0])

    monkeypatch.setattr(eng, "_get_client", lambda: _Cliente())
    monkeypatch.setattr(eng, "_get_cached", lambda key: None)
    monkeypatch.setattr(eng, "_set_cache", lambda key, result: None)
    monkeypatch.setattr(claude_engine.settings, "ANTHROPIC_MODEL", "test-model", raising=False)
    monkeypatch.setattr(claude_engine.settings, "ANTHROPIC_GUARD_MODEL", "test-judge",
                        raising=False)
    res = asyncio.run(eng.generate(context=contexto, template="anio_por_trimestres",
                                   mode="deep", axis="banking", audience="comite_credito"))
    return res.text, llamadas


def test_el_motor_repara_una_lectura_con_cifras(monkeypatch):
    texto, llamadas = _generar(monkeypatch, [
        "El año se deterioró. Cerró en 63.49, por encima de 64.15.",
        "El año se deterioró en el segundo trimestre."], {CLAVE: True, "entidad": "X"})
    assert len(llamadas) == 2, "un intento y una reparación"
    assert "CORRECCIÓN OBLIGATORIA — CIFRAS EN LA LECTURA" in llamadas[1]
    assert "63.49" in llamadas[1].partition("CIFRAS EN LA LECTURA")[2]
    assert texto == "El año se deterioró en el segundo trimestre."


def test_si_insiste_se_quita_la_oracion(monkeypatch):
    texto, _ = _generar(monkeypatch, [
        "El año se deterioró. Cerró en 63.49, por encima de 64.15."],
        {CLAVE: True, "entidad": "X"})
    assert texto == "El año se deterioró."
