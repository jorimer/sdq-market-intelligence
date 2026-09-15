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
"""
import asyncio
from types import SimpleNamespace

import pytest

from modules.banking_score.reports import anio_por_trimestres as apt


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


# ── 2 · Los términos que el dato del año no sostiene ─────────────────────────

@pytest.mark.parametrize("frase", [
    # LITERAL del PDF regenerado de Santa Cruz.
    "es la firma de un indicador que se mueve con intensidad estacional o con concentración",
    "la estacionalidad del primer trimestre explica el alza",
    "una cobertura que, si bien se mantiene por encima del umbral mínimo, se erosionó",
])
def test_se_detectan_los_terminos_vetados_del_anio(frase):
    assert apt.terminos_vetados_en_el_anio(frase)


def test_una_lectura_limpia_no_se_marca():
    assert apt.terminos_vetados_en_el_anio(
        "El segundo trimestre fue atípico frente a su historia y frente al sistema; la "
        "cobertura supera el nivel de referencia del modelo.") == []


def test_quitar_solo_la_oracion_que_especula():
    texto = ("El segundo trimestre cayó 3.50 puntos. Es la firma de un indicador estacional. "
             "La liquidez mejoró.")
    limpio = apt.quitar_oraciones_con_terminos_vetados(texto)
    assert "estacional" not in limpio
    assert "cayó 3.50 puntos" in limpio and "La liquidez mejoró." in limpio


# ── 3 · Por la RUTA del producto, no por la función ──────────────────────────

def _snapshot():
    from shared.products import ProductSnapshot, ProductTier
    return ProductSnapshot(tier=ProductTier.deep_dive, period="2025",
                           payload={"anio_por_trimestres": {"anio": 2025, "serie": []}},
                           entity_name="Banco Múltiple Santa Cruz")


def _narrar(monkeypatch, textos):
    from shared.narrative import claude_engine
    from modules.banking_score.products import BankingProduct
    from shared.products import ProductTier

    llamadas = []

    async def _fake_generate(*, context, template, mode, axis, audience):
        llamadas.append(context)
        return SimpleNamespace(text=textos[min(len(llamadas), len(textos)) - 1])

    monkeypatch.setattr(claude_engine.narrative_engine, "generate", _fake_generate)
    salida = asyncio.run(BankingProduct().narratives(ProductTier.deep_dive, _snapshot()))
    return salida["anio_por_trimestres"], llamadas


def test_la_ruta_regenera_con_la_correccion_y_entrega_el_texto_limpio(monkeypatch):
    texto, llamadas = _narrar(monkeypatch, [
        "El año cayó. Es un indicador de intensidad estacional.",
        "El año cayó en el segundo trimestre, atípico frente a su historia."])
    assert len(llamadas) == 2, "tenía que regenerar una vez"
    assert "correccion_de_terminos" in llamadas[1]
    assert "estacional" not in texto and "atípico frente a su historia" in texto


def test_si_insiste_la_especulacion_se_quita_y_el_resto_se_entrega(monkeypatch):
    texto, llamadas = _narrar(monkeypatch, [
        "El año cayó. Es estacional.", "El año cayó 3.50 puntos. Sigue siendo estacional."])
    assert len(llamadas) == 2
    assert "estacional" not in texto and "cayó 3.50 puntos" in texto
