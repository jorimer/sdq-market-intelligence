"""Lo prospectivo deja de ser brecha automática — pero solo si la proyección pasa el gate.

`_forward_gaps` declaraba brecha ante CUALQUIER pregunta a futuro: «no se estima». Era lo
correcto mientras no existía una vía legítima al otro lado del `if`. Ahora existe, y la
brecha tiene que consultarla antes de declararse.

Lo que no cambia: una proyección que no pasa el gate sigue siendo brecha. Lo que sí cambia es
que la nota diga POR QUÉ — «no se estima» a secas deja al lector sin saber si es que no hay
modelo, o que el que hay no está validado.
"""
from shared.registry.projection import MIN_OOS
from shared.registry.signals import PROJECTED, ProjectionMeta
from shared.research.models import SubQuestion
from shared.research.orchestrator import _forward_gaps
from shared.data.medida_de_pronostico import DLOG_PCT

# Tiene que ser una pregunta que `is_forward_looking` reconozca de verdad: con una que no
# reconoce, los cuatro tests pasarían sin ejercitar nada — la aserción de ausencia que se
# satisface sola.
PREGUNTA = "¿Cuál es la proyección del PIB para 2026?"


def _meta(**cambios):
    base = dict(
        model_id="bridge.m2.v1", target_series="s", horizon="2026-Q4", as_of="2026-08-31",
        revision=0, point=3.9, measure=DLOG_PCT, intervals=((0.80, 3.1, 4.7),),
        backtest_id="bridge.m2.v1|s|2026-Q4",
        oos_error=0.6, error_metric="rmse", n_oos=16, n_oos_overlapping=False,
        interval_coverage=((0.80, 0.78, 16),))
    base.update(cambios)
    return ProjectionMeta(**base)


class _Pull:
    sector_key = "macro"
    evidence = ()


def test_sin_proyeccion_sigue_declarando_la_brecha():
    brechas = _forward_gaps(PREGUNTA, [SubQuestion(text=PREGUNTA)], [_Pull()])
    assert len(brechas) == 1
    assert "no se estima" in brechas[0].note.lower()


def test_con_una_proyeccion_admisible_ya_no_hay_brecha():
    sq = SubQuestion(text=PREGUNTA, state=PROJECTED, projection=_meta())
    assert _forward_gaps(PREGUNTA, [sq], [_Pull()]) == []


def test_una_proyeccion_que_no_pasa_el_gate_sigue_siendo_brecha_Y_DICE_POR_QUE():
    sq = SubQuestion(text=PREGUNTA, state=PROJECTED, projection=_meta(n_oos=MIN_OOS - 1))
    brechas = _forward_gaps(PREGUNTA, [sq], [_Pull()])
    assert len(brechas) == 1
    nota = brechas[0].note.lower()
    assert "fuera de muestra" in nota, (
        f"la brecha no dice por qué se descartó la proyección: «{brechas[0].note}»")


def test_una_pregunta_que_no_es_prospectiva_no_declara_nada():
    assert _forward_gaps("¿Cuál fue el PIB de 2024?", [SubQuestion(text="x")], [_Pull()]) == []
