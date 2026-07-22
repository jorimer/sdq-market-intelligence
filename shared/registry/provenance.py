"""Prosa de PROCEDENCIA generada desde el registro — no escrita a mano.

Por qué existe (lección del Hallazgo 7, 2026-07-22): un texto curado que **afirma** de qué
está hecho el índice ("es dato real", "corre sobre rúbrica") envejece solo, sin que nadie
lo toque, porque cada conector nuevo lo vuelve un poco más falso. Pasó en los dos sentidos
a la vez: el ``rationale`` del IAI declaraba como rúbrica cuatro variables que ya eran
reales, mientras el prompt de doctrina del IRC afirmaba "100% dato real" de un índice cuya
dimensión de transición cae a rúbrica cada vez que el sync de Ember falla.

La conclusión que ordena este módulo: **la procedencia no es un hecho que se pueda
escribir, es un estado que cambia en cada corrida.** Por lo tanto:

- La prosa curada (``rationale`` de la doctrina) declara solo lo DURABLE: qué mide la
  dimensión y por qué pesa lo que pesa. Eso no caduca.
- La frase de procedencia se GENERA acá, desde el mismo registro que gobierna el gate de
  honestidad. No puede divergir de la verdad porque no es una segunda fuente de verdad.
- Un gate de CI (``shared/knowledge/corpus/tests``) impide que el vocabulario de
  procedencia vuelva a colarse en la prosa curada.

Registro neutro (docs REPORT_STANDARD + ``REGISTER_NEUTRO``): español latinoamericano sin
anglicismos, tono advisory, sin adjetivos de venta.
"""
from __future__ import annotations

from typing import Iterable, List, Optional, Sequence

from shared.registry.signals import (
    GAP,
    NATIONAL,
    REAL,
    RUBRIC,
    AxisRegistry,
    VariableSignal,
)


def _pct(x: float) -> str:
    return f"{round(float(x) * 100):.0f}%"


def _join(items: Sequence[str]) -> str:
    """Enumera en español: "a", "a y b", "a, b y c"."""
    items = [i for i in items if i]
    if not items:
        return ""
    if len(items) == 1:
        return items[0]
    return f"{', '.join(items[:-1])} y {items[-1]}"


def _labels(signals: Iterable[VariableSignal]) -> List[str]:
    return [(s.label or s.key) for s in signals]


def coverage_sentence(axis: AxisRegistry) -> str:
    """Una frase con la cobertura real ponderada del eje. Es el titular de procedencia."""
    cov = axis.coverage_real
    return (f"{_pct(cov)} del peso de este índice se sostiene en dato real con fuente "
            f"citable; el resto se declara como supuesto de casa o como brecha, y nunca "
            f"se completa con un valor fabricado.")


def scope_sentence(axis: AxisRegistry) -> str:
    """Distingue lo que DIFERENCIA entre sujetos de lo que solo sostiene el nivel.

    Es el matiz que "dato real" oculta: una variable nacional es dato real y sin embargo
    aporta la misma lectura a todos los sujetos del panel, así que no explica por qué uno
    puntúa distinto de otro. Sin esta frase, el cliente atribuye a su sector una diferencia
    que en realidad no existe.
    """
    real = [s for s in axis.signals if s.state == REAL]
    national = [s for s in real if s.scope == NATIONAL]
    if not national:
        return ""
    per_subject = [s for s in real if s.scope != NATIONAL]
    txt = (f"De las variables con dato real, {_join(_labels(national))} "
           f"{'se miden' if len(national) > 1 else 'se mide'} a nivel país: "
           f"{'aportan' if len(national) > 1 else 'aporta'} la misma lectura a todos los "
           f"casos comparados, de modo que "
           f"{'sostienen' if len(national) > 1 else 'sostiene'} el nivel del índice pero no "
           f"{'explican' if len(national) > 1 else 'explica'} las diferencias entre ellos.")
    if per_subject:
        txt += (f" Lo que sí diferencia un caso de otro es {_join(_labels(per_subject))}.")
    return txt


def limits_sentence(axis: AxisRegistry) -> str:
    """Declara explícitamente lo que HOY no es dato real, con su razón cuando la hay."""
    rubric = [s for s in axis.signals if s.state == RUBRIC]
    gap = [s for s in axis.signals if s.state == GAP]
    parts: List[str] = []
    if rubric:
        notes = {s.note for s in rubric if s.note}
        why = f" ({_join(sorted(notes))})" if notes else ""
        parts.append(
            f"{_join(_labels(rubric))} {'siguen' if len(rubric) > 1 else 'sigue'} siendo un "
            f"supuesto neutral de casa{why}: se declara como tal y no discrimina entre casos.")
    if gap:
        parts.append(
            f"{_join(_labels(gap))} no {'tienen' if len(gap) > 1 else 'tiene'} dato en este "
            f"período y se {'reportan' if len(gap) > 1 else 'reporta'} como brecha, no como cero.")
    return " ".join(parts)


def partial_coverage_sentence(axis: AxisRegistry) -> str:
    """Declara la parcialidad de una variable real que solo cubre a algunos sujetos."""
    partial = [s for s in axis.signals
               if s.state == REAL and 0.0 < float(s.real_fraction) < 1.0]
    if not partial:
        return ""
    detail = _join([f"{s.label or s.key} ({_pct(s.real_fraction)} de los casos)"
                    for s in partial])
    return (f"Con cobertura parcial: {detail}. Donde la fuente no llega, la variable queda "
            f"ausente en vez de rellenarse.")


def provenance_paragraph(axis: Optional[AxisRegistry]) -> str:
    """El párrafo completo de procedencia del eje, listo para la sección de Metodología.

    Devuelve cadena vacía si el eje no expone señal por-variable — silencio honesto antes
    que una afirmación que no podemos sostener.
    """
    if axis is None or not axis.signals:
        return ""
    if axis.degraded:
        # El eje no descompone por variable: solo se puede hablar a nivel agregado.
        return coverage_sentence(axis)
    parts = [
        coverage_sentence(axis),
        partial_coverage_sentence(axis),
        scope_sentence(axis),
        limits_sentence(axis),
    ]
    return " ".join(p for p in parts if p)


def provenance_for_sector(db, sector_key: str) -> str:
    """Párrafo de procedencia de un sector, resuelto contra el registro en vivo.

    Defensivo por construcción: cualquier fallo devuelve cadena vacía. Es una sección
    informativa del reporte — nunca debe tumbar la entrega.
    """
    try:
        from shared.registry.service import build_data_registry

        registry = build_data_registry(db)
        for axis in registry.axes:
            if axis.sector_key == sector_key:
                return provenance_paragraph(axis)
    except Exception:  # noqa: BLE001 — la metodología nunca rompe el reporte
        return ""
    return ""
