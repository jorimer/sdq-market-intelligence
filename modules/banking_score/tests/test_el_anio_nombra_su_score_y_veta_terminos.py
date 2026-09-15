"""El año por dentro nombra el score GLOBAL y no deja pasar especulación que su dato niega.

Dos defectos del Deep Dive 2025 de Banco Múltiple Santa Cruz regenerado en producción
(2026-09-15), después de corregir los que objetó el funcionario del banco:

1. «El score de SOLIDEZ abrió en 64.15»: 64.15 era el score GLOBAL. La serie del año viajaba
   con la clave `score` a secas y el modelo le puso el sujeto más cercano. El sujeto viaja con
   el número o se reatribuye solo.
2. «la firma de un indicador que se mueve con intensidad ESTACIONAL», sobre dos trimestres cuyo
   rótulo computado decía «atípico frente a su historia». La instrucción lo prohibía y no
   alcanzó: una nota al modelo no es un guard. Y «umbral mínimo» para el nivel de referencia
   del modelo, que no es un mínimo de nadie.

**Un solo mecanismo de veto.** El año tuvo el suyo —detector, corrección y regeneración propios
en `products.py`— mientras el motor ya tenía uno general (`shared.narrative.terminos_vetados`).
Ahora el año DECLARA sus términos en el contexto y el lazo del guard los repara. Por eso estos
tests le piden el contexto a la RUTA y juzgan con el detector general: una lista que la ruta no
declara no veta nada, exista donde exista.
"""
import asyncio
from types import SimpleNamespace

import pytest

from modules.banking_score.reports import anio_por_trimestres as apt
from shared.narrative.terminos_vetados import CLAVE, quitar_oraciones_con, terminos_en


# ── 1 · El sujeto del score ───────────────────────────────────────────────────

def _puntos():
    return [{"period_end": c, "score": s, "resiliencia": 60.0, "banda_resiliencia": "Adecuada"}
            for c, s in (("2024-12-31", 64.15), ("2025-03-31", 67.09), ("2025-06-30", 63.59),
                         ("2025-09-30", 63.43), ("2025-12-31", 63.49))]


def test_los_tramos_nombran_el_score_GLOBAL():
    tramos = apt._tramos(_puntos())
    assert tramos, "la fixture tiene que producir tramos"
    for t in tramos:
        assert "score_global_desde" in t and "score_global_hasta" in t, t
        assert "score_desde" not in t and "score_hasta" not in t, t


def test_la_serie_del_anio_nombra_el_score_GLOBAL(monkeypatch):
    monkeypatch.setattr("modules.banking_score.scoring.amplitude.entity_trajectories",
                        lambda db, bank, n, as_of: {"overall": _puntos(), "sub": {},
                                                    "indicators": {}})
    dentro = apt.anio_por_trimestres(None, SimpleNamespace(name="Banco Múltiple Santa Cruz",
                                                           id="b1"), 2025)
    assert dentro and len(dentro["serie"]) == 5, "la fixture tiene que producir la serie"
    for p in dentro["serie"]:
        assert "score_global" in p and "score" not in p, p


# ── 2 · Los términos que el dato del año no sostiene, declarados en su CONTEXTO ──

def _snapshot(dentro=None):
    from shared.products import ProductSnapshot, ProductTier
    return ProductSnapshot(tier=ProductTier.deep_dive, period="2025",
                           payload={"anio_por_trimestres": dentro or {"anio": 2025, "serie": []}},
                           entity_name="Banco Múltiple Santa Cruz")


def _contexto_servido(monkeypatch, dentro=None):
    """El contexto que la RUTA del producto le entrega al motor para el año."""
    from modules.banking_score.products import BankingProduct
    from shared.narrative import claude_engine
    from shared.products import ProductTier

    vistos = []

    async def _fake_generate(*, context, template, mode, axis, audience):
        vistos.append(context)
        return SimpleNamespace(text="El año se movió en el segundo trimestre.")

    monkeypatch.setattr(claude_engine.narrative_engine, "generate", _fake_generate)
    asyncio.run(BankingProduct().narratives(ProductTier.deep_dive, _snapshot(dentro)))
    return vistos[0]


@pytest.mark.parametrize("frase", [
    # LITERAL del PDF regenerado de Santa Cruz.
    "es la firma de un indicador que se mueve con intensidad estacional o con concentración",
    "la estacionalidad del primer trimestre explica el alza",
    "una cobertura que, si bien se mantiene por encima del umbral mínimo, se erosionó",
    # La vuelta siguiente: la misma especulación con otras palabras.
    "respondió a factores intraanuales de calendario o de reconocimiento de ingresos",
    "un efecto calendario sobre los ingresos",
    # Lo que el patrón propio cubría con `umbral(?:es)?\s+m[ií]nimos?`: plural y sin tilde.
    "por encima de los umbrales minimos del modelo",
])
def test_la_ruta_declara_los_terminos_del_anio(monkeypatch, frase):
    assert terminos_en(_contexto_servido(monkeypatch), frase), frase


def test_una_lectura_limpia_no_se_marca(monkeypatch):
    ctx = _contexto_servido(monkeypatch)
    assert terminos_en(ctx, "intensidad estacional"), "el contexto tiene que declarar el veto"
    assert terminos_en(
        ctx, "El segundo trimestre fue atípico frente a su historia y frente al sistema; la "
             "cobertura supera el nivel de referencia del modelo.") == []


def test_cada_termino_viaja_con_su_motivo(monkeypatch):
    declarados = _contexto_servido(monkeypatch).get(CLAVE) or {}
    assert declarados, "el contexto tiene que declarar el veto"
    for termino, motivo in declarados.items():
        assert isinstance(motivo, str) and motivo.strip(), termino


def test_quitar_solo_la_oracion_que_especula(monkeypatch):
    ctx = _contexto_servido(monkeypatch)
    texto = ("El segundo trimestre cayó con fuerza. Es la firma de un indicador estacional. "
             "La liquidez mejoró.")
    limpio, _ = quitar_oraciones_con(texto, terminos_en(ctx, texto))
    assert "estacional" not in limpio
    assert "cayó con fuerza" in limpio and "La liquidez mejoró." in limpio


# ── 3 · Por la RUTA, con el MOTOR real: un solo lazo repara ──────────────────

class _Msg:
    def __init__(self, text):
        self.content = [type("C", (), {"text": text})()]
        self.usage = type("U", (), {"input_tokens": 10, "output_tokens": 20})()


def _narrar(monkeypatch, textos):
    """Narra el año por la ruta del producto con el motor REAL y un cliente falso. Devuelve
    ``(texto entregado, prompts de redacción)``; el juez responde sin hallazgos."""
    from modules.banking_score.products import BankingProduct
    from shared.narrative import claude_engine
    from shared.products import ProductTier

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
    salida = asyncio.run(BankingProduct().narratives(ProductTier.deep_dive, _snapshot()))
    return salida["anio_por_trimestres"], llamadas


def test_el_lazo_del_motor_repara_con_el_motivo_del_anio(monkeypatch):
    texto, llamadas = _narrar(monkeypatch, [
        "El año se movió en el segundo trimestre. Es un indicador de intensidad estacional.",
        "El año se movió en el segundo trimestre, atípico frente a su historia."])
    assert CLAVE in llamadas[0], "el modelo tiene que leer el veto desde el primer intento"
    assert len(llamadas) == 2, "un intento y una reparación"
    aviso = llamadas[1].partition("CORRECCIÓN OBLIGATORIA — TÉRMINOS")[2]
    assert "contexto_de_los_tramos" in aviso, "el aviso tiene que traer el MOTIVO del término"
    assert "estacional" not in texto and "atípico frente a su historia" in texto


def test_si_insiste_se_quita_la_oracion_y_nadie_mas_regenera(monkeypatch):
    texto, llamadas = _narrar(monkeypatch, [
        "El año se movió en el segundo trimestre. Sigue siendo estacional."])
    from shared.narrative.claude_engine import _MAX_REINTENTOS_GUARD
    assert len(llamadas) == 1 + _MAX_REINTENTOS_GUARD, "solo el lazo del motor regenera"
    assert not any("correccion_de_terminos" in c for c in llamadas), \
        "no queda una segunda corrección, propia del producto"
    assert "estacional" not in texto and "segundo trimestre" in texto
