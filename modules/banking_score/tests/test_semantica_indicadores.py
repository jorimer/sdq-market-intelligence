"""El SIGNIFICADO del indicador se sirve; no se deduce del score.

**El defecto que SOBREVIVIÓ a corregir la dirección numérica** (BPD 2025-12-31, §5 Liquidez,
segunda corrida del 2026-08-13). Con la brecha ya bien enunciada —«supera a ese grupo por
7.31 puntos porcentuales», correcto— la misma oración decía:

> «la entidad destina proporcionalmente MENOS de cada peso captado en préstamos que el
>  promedio de bancos múltiples […] lo que preserva margen para atender retiros»

Es la glosa de un LTD BAJO pegada a un LTD ALTO. La §7 del mismo informe lo decía bien:
«ha desplegado una proporción mayor de su base de depósitos en crédito […] lo que deja menos
margen de liquidez estructural». El informe volvió a contradecirse entre secciones, con todas
las cifras correctas.

**Por qué.** El contexto servía `raw` y `score` y nada más, así que la única pista sobre si
la cifra es buena o mala era el score. El LTD tiene ÓPTIMO INTERMEDIO (80%): su score es alto
a ambos lados, de modo que «score 98.62 ⇒ esto es bueno ⇒ glosa favorable» elige una de dos
glosas favorables opuestas, y eligió la del lado equivocado.
"""
import pytest

from modules.banking_score.reports.narrative import _build_section_context
from modules.banking_score.scoring.indicator_detail import INDICATOR_META
from modules.banking_score.scoring.weights import FEATURE_ORDER

_SCORING = {
    "overall_score": 71.76, "entity_type": "banca_multiple",
    "banda_ejecucion": "Sobresaliente", "banda_resiliencia": "Adecuada",
    "sub_components": {"liquidez": 71.49},
    "indicators": {
        "liquidez_inmediata": {"raw": 20.682, "score": 68.94, "available": True},
        "ltd": {"raw": 92.4512, "score": 98.62, "available": True},
        "liquidez_ajustada": {"raw": 37.5332, "score": 46.92, "available": True},
    },
}
_BENCH = {
    "sector_averages": {"liquidity_ratio": 20.91, "ltd": 98.67},
    "peer_groups": {"banca_multiple": {"liquidity_ratio_avg": 30.52, "ltd_avg": 85.14,
                                       "label": "bancos múltiples", "n": 16}},
}


def _ctx(section="liquidez"):
    return _build_section_context(section, "BPD", _SCORING, "2025-12-31", _BENCH)


def test_el_ltd_declara_de_que_lado_del_optimo_cayo():
    """SENSOR DE REGRESIÓN: sin esto la glosa se adivina desde el score."""
    sem = _ctx()["semantica_indicadores"]["ltd"]
    assert "ÓPTIMO INTERMEDIO" in sem["sentido_de_la_escala"]
    # La advertencia explícita: el score alto no informa el lado.
    assert "NO significa que el valor sea alto ni bajo" in sem["sentido_de_la_escala"]
    assert "POR ENCIMA" in sem["posicion_vs_optimo"], sem["posicion_vs_optimo"]
    assert "92.45" in sem["posicion_vs_optimo"] and "80" in sem["posicion_vs_optimo"]


def test_los_indicadores_monotonos_declaran_su_sentido():
    sem = _ctx()["semantica_indicadores"]
    assert "MÁS ALTO" in sem["liquidez_inmediata"]["sentido_de_la_escala"]
    assert "MÁS ALTO" in sem["liquidez_ajustada"]["sentido_de_la_escala"]
    # Un indicador monótono no inventa una posición vs óptimo que no existe.
    assert "posicion_vs_optimo" not in sem["liquidez_inmediata"]


def test_cada_indicador_declara_que_mide():
    """`mide` es lo que impide la otra mitad del error: describir el ratio al revés
    («destina menos de cada peso captado» para una cartera/depósitos alta)."""
    sem = _ctx()["semantica_indicadores"]
    assert sem["ltd"]["mide"].startswith("Cartera neta / depósitos")
    assert all(b["mide"] for b in sem.values())


def test_las_dos_superficies_reciben_la_misma_semantica():
    """La §5 (dimensión) y la §7 (panorama) deben leer lo MISMO. Si solo una la tuviera,
    el informe podría volver a contradecirse entre secciones — que es la forma exacta en
    que el cliente encontró el defecto, las dos veces."""
    dim = _ctx("liquidez")["semantica_indicadores"]["ltd"]
    panorama = _ctx("risk_assessment")["semantica_indicadores"]["ltd"]
    assert dim == panorama


@pytest.mark.parametrize("key", [k for k, m in INDICATOR_META.items()
                                 if m.get("direction") == "target"])
def test_todo_indicador_de_optimo_intermedio_tiene_el_optimo_numerico(key):
    """El óptimo vivía solo dentro del texto de `que` («óptimo ~80%»), que no se puede
    computar. Un `target` sin `optimo` deja al modelo otra vez adivinando el lado."""
    assert isinstance(INDICATOR_META[key].get("optimo"), (int, float)), (
        f"{key} es de óptimo intermedio pero no declara `optimo` numérico")


def test_ningun_indicador_del_motor_queda_sin_semantica():
    """PRUEBA NEGATIVA de cobertura: un indicador que el motor puntúa pero que no está en
    INDICATOR_META saldría del bloque en silencio y volvería a narrarse a ciegas."""
    faltan = [k for k in FEATURE_ORDER
              if k not in INDICATOR_META and not k.startswith("composite")]
    assert not faltan, f"indicadores puntuados sin metadata de significado: {faltan}"
