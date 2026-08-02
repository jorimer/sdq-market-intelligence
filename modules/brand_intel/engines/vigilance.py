"""Vigilance and agenda engine (S5) — what moved, and what deserves a meeting.

The signal panel answers "what changed since the last delivery" across three sources that
move at different speeds: the macro environment (monthly), the tracker's own indicators
(quarterly), and the frozen forecast's hits and misses.

The agenda is the synthesis, and it is the piece the client actually acts on. Its job is
subtraction: 59 charts arrive and two or three things genuinely deserve a conversation.
Everything it proposes must clear the same bar the rest of the module applies — a movement
that cannot pass its own detection threshold never reaches the agenda, no matter how large
it looks on a chart.

Ordering is by evidence strength, not by drama:

* **A forecast miss outranks everything.** It is the only signal that was committed to in
  advance and can be scored without hindsight.
* **A statistically clean finding outranks a marginal one**, and a marginal one never
  arrives alone — it arrives with a request for corroboration.
* **Macro context sets the frame; it is never an agenda item on its own.** "Inflation rose"
  is not a decision.

The cap is deliberate. An agenda that lists everything prioritises nothing.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Sequence

MAX_AGENDA_ITEMS = 4

PRIORITY_HIGH = "alta"
PRIORITY_MEDIUM = "media"
PRIORITY_LOW = "baja"

_PRIORITY_RANK = {PRIORITY_HIGH: 0, PRIORITY_MEDIUM: 1, PRIORITY_LOW: 2}


@dataclass(frozen=True)
class Signal:
    """One thing that moved, with where it came from and whether it clears its own bar."""

    source: str            # macro | tracker | forecast | decision
    label: str
    reading: str
    direction: str         # favorable | adverso | neutral | n/d
    strength: str          # confirmada | marginal | contextual
    detail: str = ""


def macro_signals(factors: Sequence[Dict[str, Any]], limit: int = 5) -> List[Signal]:
    """Macro factors as signals, worst first — the ones that set the period's frame."""
    order = {"adverso": 0, "neutral": 1, "favorable": 2, "n/d": 3}
    mag = {"alto": 0, "moderado": 1, "bajo": 2}
    usable = [f for f in factors if f.get("direction") in order]
    usable.sort(key=lambda f: (order.get(f.get("direction", "n/d"), 3),
                               mag.get(f.get("magnitude", "bajo"), 2)))
    return [
        Signal(
            "macro", f.get("label", f.get("key", "")), f.get("reading", ""),
            f.get("direction", "n/d"), "contextual",
            f.get("rationale", "") or "",
        )
        for f in usable[:limit]
    ]


def tracker_signals(assessments: Sequence[Dict[str, Any]]) -> List[Signal]:
    """Wave-over-wave movements that cleared, or nearly cleared, their own threshold.

    Anything below the threshold is deliberately dropped: it is not a weak signal, it is
    an absence of one, and carrying it forward is how noise ends up in a decision.
    """
    out: List[Signal] = []
    for a in assessments:
        verdict = a.get("verdict")
        if verdict in ("significant_up", "significant_down"):
            strength = "confirmada"
        elif verdict == "marginal":
            strength = "marginal"
        else:
            continue
        delta = a.get("delta")
        higher_better = a.get("higher_is_better", True)
        direction = ("neutral" if delta is None
                     else "favorable" if (delta > 0) == higher_better else "adverso")
        out.append(Signal(
            "tracker", a.get("label", a.get("metric_code", "")),
            f"{delta:+.1f} pp" if delta is not None else "n/d",
            direction, strength, a.get("note", ""),
        ))
    return out


def forecast_signals(scored: Sequence[Dict[str, Any]]) -> List[Signal]:
    """Forecast misses. The only signal committed to before the data existed."""
    out: List[Signal] = []
    for s in scored:
        if s.get("inside_band"):
            continue
        actual, point = s.get("actual"), s.get("point")
        direction = ("neutral" if actual is None or point is None
                     else "favorable" if actual > point else "adverso")
        out.append(Signal(
            "forecast", s.get("label", s.get("metric", "")),
            f"{actual:.1f}% vs {point:.1f}% pronosticado"
            if actual is not None and point is not None else "n/d",
            direction, "confirmada", s.get("note", ""),
        ))
    return out


def decision_signals(decisions: Sequence[Dict[str, Any]]) -> List[Signal]:
    """Decisions that closed badly or landed in the noise. NOT the unevaluable ones:
    "no puede medirse" es un estado estático, no un movimiento — con un plan adoptado
    entero (100+ compromisos) emitir una señal por cada inevaluable inunda el panel
    con filas idénticas que no cambiaron desde la última entrega ni cambiarán."""
    out: List[Signal] = []
    for d in decisions:
        status = d.get("status")
        if status == "worsened":
            strength, direction = "confirmada", "adverso"
        elif status == "not_detectable":
            strength, direction = "marginal", "neutral"
        else:
            continue
        out.append(Signal(
            "decision", d.get("title", ""),
            d.get("label", ""), direction, strength, d.get("note", ""),
        ))
    return out


@dataclass
class AgendaItem:
    title: str
    priority: str
    rationale: str
    evidence: List[str] = field(default_factory=list)
    source: str = ""


def build_agenda(
    forecast_sigs: Sequence[Signal],
    tracker_sigs: Sequence[Signal],
    decision_sigs: Sequence[Signal],
    divergence_reading: Optional[Dict[str, Any]],
    environment_note: Optional[str],
    weakest_step: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Assemble the quarter's agenda from everything that cleared its bar."""
    items: List[AgendaItem] = []

    for s in forecast_sigs:
        items.append(AgendaItem(
            title=f"Desvío no anticipado en {s.label}",
            priority=PRIORITY_HIGH,
            rationale="El resultado cayó fuera de la banda pronosticada antes del campo. "
                      "Es el único tipo de señal comprometida por adelantado.",
            evidence=[s.reading, s.detail],
            source="forecast",
        ))

    for s in tracker_sigs:
        if s.strength != "confirmada":
            continue
        items.append(AgendaItem(
            title=f"Movimiento confirmado en {s.label}",
            priority=PRIORITY_HIGH if s.direction == "adverso" else PRIORITY_MEDIUM,
            rationale="El movimiento supera el umbral detectable de su propia base.",
            evidence=[s.reading, s.detail],
            source="tracker",
        ))

    for s in decision_sigs:
        if s.strength != "confirmada":
            continue
        items.append(AgendaItem(
            title=f"Decisión con retroceso: {s.label}",
            priority=PRIORITY_MEDIUM,
            rationale="Una decisión comprometida cerró con la métrica en contra.",
            evidence=[s.detail],
            source="decision",
        ))

    if divergence_reading and divergence_reading.get("diverging"):
        up = divergence_reading["direction"] == "converting_above_attitude"
        items.append(AgendaItem(
            title=("Preferencia declarada por debajo de la conversión" if up
                   else "Conversión por debajo de la preferencia declarada"),
            priority=PRIORITY_MEDIUM,
            rationale=("La marca convierte por encima de su capital actitudinal: sostenible "
                       "mientras dure la base instalada, expuesto si la preferencia no se repone."
                       if up else
                       "Hay intención declarada que no se traduce en visita: el problema está "
                       "entre la consideración y la conversión, no en la notoriedad."),
            evidence=[f"preferencia {divergence_reading['delta_attitude']:+.1f} pp, "
                      f"tráfico {divergence_reading['delta_behaviour']:+.1f} pp"],
            source="category",
        ))

    if weakest_step and weakest_step.get("gap") is not None:
        items.append(AgendaItem(
            title=f"Escalón de rezago: {weakest_step['step_label']}",
            priority=PRIORITY_MEDIUM,
            rationale="Es el punto del embudo donde la marca cede más terreno frente al "
                      "mejor del set; concentra la pérdida.",
            evidence=[f"{weakest_step['focal_conversion']:.0f}% frente a "
                      f"{weakest_step['leader_conversion']:.0f}% de "
                      f"{weakest_step.get('leader_name', weakest_step.get('leader', ''))} "
                      f"(brecha {weakest_step['gap']:.1f} pp)"],
            source="funnel",
        ))

    marginal = [s for s in tracker_sigs if s.strength == "marginal"]
    if marginal:
        items.append(AgendaItem(
            title="Señales en el filo, pendientes de corroboración",
            priority=PRIORITY_LOW,
            rationale="Movimientos que apenas rozan su umbral. No sostienen una decisión "
                      "por sí solos; requieren una fuente independiente antes de accionar.",
            evidence=[f"{s.label}: {s.reading}" for s in marginal[:3]],
            source="tracker",
        ))

    items.sort(key=lambda i: _PRIORITY_RANK[i.priority])
    dropped = max(0, len(items) - MAX_AGENDA_ITEMS)

    return {
        "items": [
            {"title": i.title, "priority": i.priority, "rationale": i.rationale,
             "evidence": [e for e in i.evidence if e], "source": i.source}
            for i in items[:MAX_AGENDA_ITEMS]
        ],
        "dropped": dropped,
        "frame": environment_note,
        "note": (
            f"{dropped} punto(s) adicional(es) quedaron fuera del corte de "
            f"{MAX_AGENDA_ITEMS}: una agenda que lista todo no prioriza nada."
            if dropped else
            "Ningún punto quedó fuera del corte."
        ),
        "empty_reason": (
            None if items else
            "Ningún indicador superó su umbral de detección, ningún pronóstico se desvió "
            "de su banda y ninguna decisión cerró en contra. El trimestre no justifica "
            "una reunión de resultados."
        ),
    }
