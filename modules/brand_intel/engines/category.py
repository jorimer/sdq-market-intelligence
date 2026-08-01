"""Category engine — the denominator the tracker does not build.

A brand tracker measures the numerator: what the consumer thinks and declares about each
brand. It rarely states how big the category itself is, so a brand can lose declared
preference while gaining ground, or gain preference inside a shrinking category, and the
report reads the same either way.

This engine builds the denominator from reach-type metrics and derives:

* **Category size** — the sum of reach across the brands flagged as in-set.
* **Share of category** — each brand's slice, wave by wave.
* **Share shift** — who gained ground and, by arithmetic, at whose expense.
* **Attitude vs behaviour** — declared preference against effective traffic share. When
  these two diverge, the divergence *is* the diagnosis, and neither series alone shows it.

Everything here is a pure function over plain structures: no database, no ORM. The service
layer loads cells and calls in. That is what makes the arithmetic testable in isolation.

**Honest bound, carried into the report:** this is share of *declared reach within the
measured set*, not market share. It excludes independents, informal trade and any chain
outside the study. The reports must say so wherever the number appears.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Sequence, Tuple


@dataclass(frozen=True)
class Cell:
    """One observation, flattened for the engines."""

    wave: str                      # wave code, e.g. "2026-03"
    brand: Optional[str]           # brand slug; None = category-level
    value: float
    base_n: Optional[int] = None


@dataclass(frozen=True)
class SharePoint:
    wave: str
    brand: str
    reach: float
    share: float


def _by_wave(cells: Sequence[Cell]) -> Dict[str, Dict[str, float]]:
    out: Dict[str, Dict[str, float]] = {}
    for c in cells:
        if c.brand is None:
            continue
        out.setdefault(c.wave, {})[c.brand] = c.value
    return out


#: Cuántas marcas medidas hacen falta para que la suma sea una categoría.
#: Con una sola, el denominador ES esa marca: su share sale 100% por construcción y la
#: "categoría" crece cuando en la ola siguiente entran las demás. No es un hallazgo, es un
#: artefacto de cobertura — y salió impreso como titular de un informe.
MIN_DENOMINATOR_BRANDS = 2


def measured_by_wave(
    cells: Sequence[Cell], in_set: Optional[Sequence[str]] = None
) -> Dict[str, Dict[str, float]]:
    """Alcance por ola y marca, restringido al set declarado."""
    allowed = set(in_set) if in_set is not None else None
    out: Dict[str, Dict[str, float]] = {}
    for wave, brands in _by_wave(cells).items():
        kept = {b: v for b, v in brands.items() if allowed is None or b in allowed}
        if kept:
            out[wave] = kept
    return out


def category_size(
    cells: Sequence[Cell], in_set: Optional[Sequence[str]] = None
) -> Dict[str, Optional[float]]:
    """Suma del alcance de las marcas del set, por ola.

    No es una estimación de población: es un índice de actividad de la categoría, y su
    valor es comparativo. Una ola con menos de ``MIN_DENOMINATOR_BRANDS`` marcas medidas
    devuelve ``None`` en vez de una cifra — con una sola marca la suma no es una categoría
    y todo lo que se derive de ella (share, crecimiento) es falso, no impreciso.
    """
    return {
        wave: (sum(brands.values())
               if len(brands) >= MIN_DENOMINATOR_BRANDS else None)
        for wave, brands in measured_by_wave(cells, in_set).items()
    }


def comparable_size(
    cells: Sequence[Cell], waves: Sequence[str], in_set: Optional[Sequence[str]] = None
) -> Tuple[Dict[str, Optional[float]], List[str]]:
    """Tamaño de categoría sobre el conjunto de marcas medido en TODAS las olas dadas.

    El crecimiento entre dos olas solo significa algo si el denominador está hecho de las
    mismas marcas: si en mayo hay una marca medida y en marzo cuatro, la "categoría" crece
    porque medimos más, no porque haya más consumo. Devuelve también qué marcas
    sostuvieron la comparación, porque el informe tiene que poder decirlo.
    """
    grid = measured_by_wave(cells, in_set)
    presentes = [grid[w] for w in waves if w in grid]
    if len(presentes) < 2:
        return {}, []
    comun = set(presentes[0])
    for otra in presentes[1:]:
        comun &= set(otra)
    if len(comun) < MIN_DENOMINATOR_BRANDS:
        return {}, sorted(comun)
    sizes: Dict[str, Optional[float]] = {
        w: sum(v for b, v in grid[w].items() if b in comun)
        for w in waves if w in grid
    }
    return sizes, sorted(comun)


def share_by_brand(
    cells: Sequence[Cell], in_set: Optional[Sequence[str]] = None
) -> List[SharePoint]:
    """Each in-set brand's share of the category, per wave."""
    grid = _by_wave(cells)
    sizes = category_size(cells, in_set)
    allowed = set(in_set) if in_set is not None else None
    out: List[SharePoint] = []
    for wave, brands in grid.items():
        total = sizes.get(wave)
        # Una ola sin denominador válido no produce share: repartir sobre una sola marca
        # da 100% por construcción, que es peor que no decir nada.
        if not total or total <= 0:
            continue
        for brand, reach in brands.items():
            if allowed is not None and brand not in allowed:
                continue
            out.append(SharePoint(wave, brand, reach, reach / total * 100.0))
    return out


def category_growth(
    sizes: Dict[str, Optional[float]], waves: Sequence[str]
) -> Optional[float]:
    """Variación del tamaño de categoría entre la primera y la última ola con dato.

    Las olas sin denominador válido no entran: compararse contra una ola cuyo tamaño es
    el de una sola marca no mide crecimiento, mide cobertura.
    """
    ordered = [w for w in waves if sizes.get(w) is not None]
    if len(ordered) < 2:
        return None
    first, last = sizes[ordered[0]], sizes[ordered[-1]]
    if not first or last is None:
        return None
    return (last / first - 1.0) * 100.0


def share_shift(
    points: Sequence[SharePoint], waves: Sequence[str]
) -> List[Dict[str, Any]]:
    """Share change per brand between the first and last wave, ranked by gain.

    The arithmetic identity behind the reading: shares sum to 100, so the gainers' total
    equals the losers' total. That is what licenses saying a rival's growth "came from"
    particular brands — not a causal claim, an accounting one, and the report says so.
    """
    ordered = [w for w in waves if any(p.wave == w for p in points)]
    if len(ordered) < 2:
        return []
    first, last = ordered[0], ordered[-1]
    idx: Dict[str, Dict[str, float]] = {}
    for p in points:
        if p.wave in (first, last):
            idx.setdefault(p.brand, {})[p.wave] = p.share
    rows: List[Dict[str, Any]] = [
        {
            "brand": brand,
            "share_first": vals[first],
            "share_last": vals[last],
            "delta": vals[last] - vals[first],
        }
        for brand, vals in idx.items()
        if first in vals and last in vals
    ]
    rows.sort(key=lambda r: r["delta"], reverse=True)
    return rows


@dataclass(frozen=True)
class DivergencePoint:
    wave: str
    attitude: Optional[float]      # declared preference
    behaviour: Optional[float]     # effective share of category traffic


def attitude_vs_behaviour(
    attitude_cells: Sequence[Cell],
    behaviour_points: Sequence[SharePoint],
    brand: str,
    waves: Sequence[str],
) -> List[DivergencePoint]:
    """Declared preference against effective traffic share, aligned wave by wave."""
    att = {c.wave: c.value for c in attitude_cells if c.brand == brand}
    beh = {p.wave: p.share for p in behaviour_points if p.brand == brand}
    return [DivergencePoint(w, att.get(w), beh.get(w)) for w in waves]


def divergence_reading(points: Sequence[DivergencePoint]) -> Optional[Dict[str, object]]:
    """Whether attitude and behaviour moved in opposite directions in the last step.

    Returns None when either series is incomplete — an absent reading rather than a
    guessed one.
    """
    # Unpacked into plain floats rather than filtered in place: the guard and the
    # arithmetic then live in the same expression, so a later edit cannot separate them.
    usable = [(p.wave, p.attitude, p.behaviour) for p in points
              if p.attitude is not None and p.behaviour is not None]
    if len(usable) < 2:
        return None
    (prev_wave, att_prev, beh_prev) = usable[-2]
    (curr_wave, att_curr, beh_curr) = usable[-1]
    d_att = att_curr - att_prev
    d_beh = beh_curr - beh_prev
    diverging = (d_att > 0) != (d_beh > 0) and d_att != 0 and d_beh != 0
    return {
        "wave_from": prev_wave,
        "wave_to": curr_wave,
        "delta_attitude": d_att,
        "delta_behaviour": d_beh,
        "diverging": diverging,
        "direction": (
            "converting_above_attitude" if diverging and d_beh > 0
            else "attitude_above_conversion" if diverging
            else "aligned"
        ),
    }


def attribution(
    brand_delta: Optional[float],
    category_delta_pct: Optional[float],
    brand_value_prev: Optional[float],
) -> Optional[Dict[str, float]]:
    """Split a brand's movement into what the category explains and what it does not.

    ``category_effect`` is the movement the brand would have shown by merely holding its
    share while the category moved; ``brand_effect`` is the residual — the part that is
    the brand's own. It is a decomposition, not a causal model, and it answers the
    question that decides whether to act: did we move, or did the market move under us?
    """
    if brand_delta is None or category_delta_pct is None or not brand_value_prev:
        return None
    category_effect = brand_value_prev * (category_delta_pct / 100.0)
    return {
        "total_delta": brand_delta,
        "category_effect": category_effect,
        "brand_effect": brand_delta - category_effect,
    }
