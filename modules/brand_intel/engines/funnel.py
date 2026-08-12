"""Funnel engine — where the brand actually leaks.

A tracker reports each rung of the ladder (awareness, ever tried, last 3 months, last
month, last 7 days) as a separate number. Conversion *between* rungs is where the
diagnosis lives: a brand can lead awareness and still lose, because the loss happens one
step later.

Step conversion normalises brand size away, so a small brand and a large one are
comparable rung by rung — which is what makes "our weakest step versus the set's best" a
usable statement.
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Sequence, Tuple

from modules.brand_intel.engines.metrics import FUNNEL_LADDER, label_for


@dataclass(frozen=True)
class FunnelStep:
    from_metric: str
    to_metric: str
    label: str
    conversion: Optional[float]     # percent


@dataclass(frozen=True)
class BrandFunnel:
    brand: str
    rungs: Dict[str, Optional[float]]
    steps: List[FunnelStep]
    end_to_end: Optional[float]


def build_funnel(brand: str, rungs: Dict[str, Optional[float]]) -> BrandFunnel:
    """Conversion at each rung of the ladder for one brand, in one wave."""
    steps: List[FunnelStep] = []
    for a, b in zip(FUNNEL_LADDER, FUNNEL_LADDER[1:]):
        va, vb = rungs.get(a), rungs.get(b)
        conv = (vb / va * 100.0) if va and vb is not None and va > 0 else None
        steps.append(FunnelStep(a, b, f"{label_for(a)} → {label_for(b)}", conv))

    first, last = rungs.get(FUNNEL_LADDER[0]), rungs.get(FUNNEL_LADDER[-1])
    e2e = (last / first * 100.0) if first and last is not None and first > 0 else None
    return BrandFunnel(brand, rungs, steps, e2e)


def weakest_step(focal: BrandFunnel, peers: Sequence[BrandFunnel]) -> Optional[Dict[str, object]]:
    """The rung where the focal brand trails the set's best by the widest margin.

    Returns the gap and who sets the benchmark. This is the single most actionable output
    of the funnel: it names *which* step to fix rather than restating that the brand is
    behind overall.
    """
    best_gap: Optional[Dict[str, Any]] = None
    best_value: Optional[float] = None
    for i, step in enumerate(focal.steps):
        if step.conversion is None:
            continue
        # Built with an explicit loop rather than a comprehension so the None check and
        # the value it admits are the same expression — a filtered comprehension reads
        # the attribute twice, and only the second read reaches the arithmetic.
        rivals: List[Tuple[str, float]] = []
        for p in peers:
            if p.brand == focal.brand or i >= len(p.steps):
                continue
            conv = p.steps[i].conversion
            if conv is not None:
                rivals.append((p.brand, conv))
        if not rivals:
            continue
        leader, leader_conv = max(rivals, key=lambda r: r[1])
        gap = leader_conv - step.conversion
        if best_value is None or gap > best_value:
            best_value = gap
            best_gap = {
                "step_label": step.label,
                "from_metric": step.from_metric,
                "to_metric": step.to_metric,
                "focal_conversion": step.conversion,
                "leader": leader,
                "leader_conversion": leader_conv,
                "gap": gap,
            }
    return best_gap


def step_gap_series(
    focal_by_wave: Dict[str, BrandFunnel],
    rival_by_wave: Dict[str, BrandFunnel],
    step_index: int,
    waves: Sequence[str],
) -> List[Dict[str, Any]]:
    """The same step, tracked across waves against one rival.

    A gap that holds wave after wave is structural; one that appears once is noise. This
    is what lets the report distinguish the two instead of asserting either.
    """
    rows: List[Dict[str, Any]] = []
    for w in waves:
        f = focal_by_wave.get(w)
        r = rival_by_wave.get(w)
        fc = f.steps[step_index].conversion if f and step_index < len(f.steps) else None
        rc = r.steps[step_index].conversion if r and step_index < len(r.steps) else None
        rows.append({
            "wave": w,
            "focal": fc,
            "rival": rc,
            "gap": (rc - fc) if fc is not None and rc is not None else None,
        })
    return rows


# ── la brecha ENTRE indicadores, computada y con su sujeto ─────────────

#: Qué población vive en el hueco entre dos peldaños consecutivos. La escalera es
#: ANIDADA: quien consumió en los últimos 7 días consumió también en el último mes, así
#: que la diferencia entre dos peldaños ES una proporción de la misma muestra —y por eso
#: puede llevar su propio margen de error—. El sujeto va escrito acá y no lo redacta el
#: modelo: es la regla de que el sujeto viaja con el número.
LADDER_GAP_SUBJECT: Dict[Tuple[str, str], str] = {
    ("awareness_total", "ever_tried"):
        "personas que conocen la marca pero nunca la han probado",
    ("ever_tried", "reach_3m"):
        "personas que probaron la marca alguna vez pero no la consumieron en el trimestre",
    ("reach_3m", "reach_1m"):
        "personas que consumieron en el trimestre pero no en el último mes",
    ("reach_1m", "reach_7d"):
        "personas que consumieron en el último mes pero no en los últimos 7 días",
}


def ladder_gaps(
    rungs: Dict[str, Optional[float]],
    bases: Dict[str, Optional[int]],
    z: float = 1.96,
) -> List[Dict[str, Any]]:
    """La distancia entre peldaños CONSECUTIVOS, con su margen de error y su sujeto.

    Solo se computa entre peldaños de la escalera, y solo cuando comparten base: fuera de
    esa relación de anidamiento la diferencia entre dos indicadores no tiene una
    distribución que podamos estimar —haría falta la conjunta, que el tracker no
    entrega—, y por eso ahí no hay cifra que publicar sino una comparación que no se hace.

    Un hueco negativo NO se convierte en sujeto: rompe el anidamiento y lo que hay es una
    inconsistencia del dato, que se declara en vez de interpretarse.
    """
    out: List[Dict[str, Any]] = []
    for a, b in zip(FUNNEL_LADDER, FUNNEL_LADDER[1:]):
        va, vb = rungs.get(a), rungs.get(b)
        na, nb = bases.get(a), bases.get(b)
        row: Dict[str, Any] = {
            "de": a, "a": b,
            "etiquetas": f"{label_for(a)} → {label_for(b)}",
            "valor_de": va, "valor_a": vb,
            "sujeto_de_la_brecha": LADDER_GAP_SUBJECT.get((a, b)),
        }
        if va is None or vb is None:
            row.update(brecha=None, verdicto="sin_dato",
                       nota="Uno de los dos peldaños no tiene dato en esta ola.")
        elif not na or not nb or na != nb:
            row.update(brecha=round(va - vb, 2), verdicto="no_computable",
                       nota=("Los dos peldaños no comparten base muestral: la diferencia "
                             "no puede leerse como una subpoblación."))
        elif va < vb:
            row.update(brecha=round(va - vb, 2), verdicto="inconsistente",
                       nota=(f"El peldaño posterior supera al anterior "
                             f"({vb}% > {va}%): el anidamiento no se cumple y la "
                             "diferencia no describe ninguna población."))
        else:
            d = (va - vb) / 100.0
            margen = z * math.sqrt(d * (1.0 - d) / na) * 100.0
            gap = va - vb
            row.update(
                brecha=round(gap, 2), base_n=na,
                margen_de_error=round(margen, 2),
                verdicto=("distinguible_de_cero" if gap > margen
                          else "no_distinguible_de_cero"),
                nota=("La brecha es una proporción de la misma muestra; su margen al 95% "
                      f"es ±{round(margen, 2)} pp."),
            )
        out.append(row)
    return out
