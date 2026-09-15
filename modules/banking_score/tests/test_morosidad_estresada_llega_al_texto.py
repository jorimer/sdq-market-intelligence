"""La morosidad estresada llega al CONTEXTO que escribe el texto, en la dimensión correcta.

Un bloque bien computado que no viaja al modelo es el defecto de «servir el dato no alcanza»:
el informe sigue hablando solo de la mora convencional. Estos tests piden el contexto por el
constructor real de la sección, y la instrucción por la plantilla real.
"""
from modules.banking_score.reports.narrative import _build_section_context

_BLOQUE = {"disponible": True, "morosidad_estresada_de_la_entidad_pct": 7.61,
           "lo_que_la_mora_convencional_no_ve_pp": 5.49,
           "posicion_frente_a_la_mediana_del_resto": "por encima"}


def _scoring(**extra):
    return {"overall_score": 63.8, "sub_components": {"calidad": 55.0, "solidez": 70.0},
            "indicators": {"morosidad": {"raw": 2.97, "score": 60.0},
                           "castigos_pct": {"raw": 3.67, "score": 0.0}},
            **extra}


def test_la_seccion_de_calidad_recibe_el_bloque():
    ctx = _build_section_context("calidad_activos", "Banco Múltiple Santa Cruz",
                                 _scoring(morosidad_estresada=_BLOQUE), "2025-12-31")
    assert ctx.get("morosidad_estresada") == _BLOQUE


def test_otra_dimension_NO_lo_recibe():
    """El sujeto de solidez no es la cartera: meterle la estresada invita a mezclarlas."""
    ctx = _build_section_context("solidez_financiera", "Banco Múltiple Santa Cruz",
                                 _scoring(morosidad_estresada=_BLOQUE), "2025-12-31")
    assert "sub_componente" in ctx, "la fixture tiene que armar una sección de dimensión"
    assert "morosidad_estresada" not in ctx


def test_sin_bloque_la_seccion_no_inventa_uno():
    ctx = _build_section_context("calidad_activos", "Banco Múltiple Santa Cruz",
                                 _scoring(), "2025-12-31")
    assert "sub_componente" in ctx
    assert "morosidad_estresada" not in ctx


def test_las_DOS_plantillas_que_la_leen_llevan_la_instruccion():
    from shared.narrative.claude_engine import (MOROSIDAD_ESTRESADA_EN_EL_TEXTO,
                                                THIN_TEMPLATES)

    assert "NO restes" in MOROSIDAD_ESTRESADA_EN_EL_TEXTO
    # El PDF regenerado de Santa Cruz (2026-09-15) dijo que la cobertura «se estrecha» sobre
    # la mora estresada: lo castigado ya salió del balance y no lleva provisión.
    assert "cobertura de provisiones se mide contra la mora CONVENCIONAL" in (
        MOROSIDAD_ESTRESADA_EN_EL_TEXTO)
    for plantilla in ("subcomponent_focus", "anio_por_trimestres"):
        assert MOROSIDAD_ESTRESADA_EN_EL_TEXTO in THIN_TEMPLATES[plantilla], plantilla
