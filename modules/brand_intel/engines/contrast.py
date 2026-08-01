"""Contraste: ¿las cifras confirmadas sostienen lo que el proveedor afirma?

Este motor existe por una regla de la alianza: **no se audita al proveedor delante de su
cliente**. Si SDQ va a explicar las conclusiones del proveedor con sus propios datos,
primero tiene que saber en cuáles está parado sobre terreno firme — y cuando una no se
sostiene, eso NO va al informe del cliente: va a una mesa aparte, a discutirse con el
proveedor primero. El contraste es lo que separa esas dos rutas.

El veredicto se apoya en el motor de significancia, no en una segunda opinión del modelo:
la conclusión afirma una dirección (sube/baja/estable) y las observaciones confirmadas,
con sus bases, dicen si ese movimiento es distinguible de ruido muestral. Tres salidas:

* ``coincide``   — el movimiento de los datos apunta donde el proveedor dice.
* ``discrepa``   — los datos sostienen lo contrario, con significancia. Solo esto abre
                   una discrepancia: un desacuerdo que no se puede defender con un umbral
                   delante del proveedor no es una discrepancia, es una corazonada.
* ``no_evaluable`` — falta la cifra, la base, o la conclusión no afirma movimiento.

Deliberadamente conservador en un sentido: «estable» del proveedor contra un movimiento
no-significativo de los datos es ``coincide`` — no distinguible de ruido ES estable. Y un
movimiento *marginal* nunca abre discrepancia: en el filo del umbral no se lleva una
objeción a la mesa del socio.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Sequence, Tuple

from modules.brand_intel.engines import significance as sig

#: Veredictos del contraste.
COINCIDE, DISCREPA, NO_EVALUABLE = "coincide", "discrepa", "no_evaluable"


@dataclass(frozen=True)
class Contrast:
    """El contraste de UNA conclusión contra las cifras confirmadas."""

    conclusion_id: str
    verdict: str                 # coincide | discrepa | no_evaluable
    note: str
    #: Por marca: (slug, dirección de los datos, delta, veredicto de significancia)
    per_brand: Tuple[Dict[str, Any], ...] = ()

    def as_dict(self) -> Dict[str, Any]:
        return {"conclusion_id": self.conclusion_id, "verdict": self.verdict,
                "note": self.note, "per_brand": list(self.per_brand)}


def _data_direction(assessment: sig.ChangeAssessment) -> Optional[str]:
    """Lo que los datos afirman, en el vocabulario de la conclusión.

    Solo lo significativo cuenta como movimiento: un delta por debajo del umbral es
    «estable» — no distinguible de ruido ES estable. Lo marginal y lo no evaluable
    devuelven ``None``: los datos no afirman nada utilizable.
    """
    if assessment.verdict == sig.SIGNIFICANT_UP:
        return "sube"
    if assessment.verdict == sig.SIGNIFICANT_DOWN:
        return "baja"
    if assessment.verdict == sig.NOT_DETECTABLE:
        return "estable"
    return None


def contrast_conclusion(
    conclusion: Any,
    series: Dict[Tuple[str, str], List[Tuple[str, Optional[float], Optional[int]]]],
    wave_order: Sequence[str],
) -> Contrast:
    """Contrasta una conclusión con dirección contra la serie confirmada.

    ``series`` mapea (brand_slug, metric_code) → [(wave_code, value, base_n)] en orden
    cronológico. El movimiento juzgado es el de la ola que la conclusión nombra contra la
    anterior; si no nombra ola, el de las dos últimas — que es lo que un mazo de tracker
    está comentando cuando no dice más.
    """
    cid = str(conclusion.id)
    direction = (conclusion.direction or "").strip()
    slugs = list(conclusion.subject_slugs or [])
    metric = conclusion.metric_code

    if not direction or not slugs or not metric:
        return Contrast(cid, NO_EVALUABLE,
                        "La conclusión no afirma un movimiento contrastable "
                        "(sin dirección, sin marca resuelta o sin métrica).")

    per_brand: List[Dict[str, Any]] = []
    data_dirs: List[str] = []
    for slug in slugs:
        pts = series.get((slug, metric), [])
        pair = _pair_for(pts, conclusion.wave_code, wave_order)
        if pair is None:
            per_brand.append({"brand": slug, "data_direction": None, "delta": None,
                              "verdict": "sin_serie",
                              "note": "No hay dos olas confirmadas para esta métrica."})
            continue
        (pv, pb), (cv, cb) = pair
        a = sig.assess_change(metric, pv, pb, cv, cb)
        d = _data_direction(a)
        per_brand.append({"brand": slug, "data_direction": d, "delta": a.delta,
                          "verdict": a.verdict, "note": a.note})
        if d is not None:
            data_dirs.append(d)

    if not data_dirs:
        return Contrast(cid, NO_EVALUABLE,
                        "Las cifras confirmadas no alcanzan para juzgar el movimiento "
                        "(falta serie, base, o el veredicto quedó en el filo).",
                        tuple(per_brand))

    # La conclusión habla de todas sus marcas a la vez; el contraste la juzga igual.
    # DISCREPA exige que NINGUNA marca evaluable acompañe al proveedor y al menos una lo
    # contradiga de frente — sube contra baja, no sube contra estable. Si alguna marca
    # coincide, la conclusión se sostiene parcialmente y eso no se lleva a la mesa.
    if any(d == direction for d in data_dirs):
        return Contrast(cid, COINCIDE,
                        "Las cifras confirmadas acompañan el movimiento afirmado.",
                        tuple(per_brand))
    frontal = {"sube": "baja", "baja": "sube"}.get(direction)
    if frontal and frontal in data_dirs:
        return Contrast(cid, DISCREPA,
                        "Las cifras confirmadas sostienen el movimiento contrario, con "
                        "significancia. Para discutir con el proveedor antes de usarse.",
                        tuple(per_brand))
    if direction == "estable" and data_dirs:
        # El proveedor dice estable y los datos dicen movimiento significativo.
        return Contrast(cid, DISCREPA,
                        "El proveedor afirma estabilidad; las cifras confirmadas "
                        "sostienen un movimiento significativo.",
                        tuple(per_brand))
    return Contrast(cid, NO_EVALUABLE,
                    "Los datos afirman estabilidad donde el proveedor afirma movimiento: "
                    "por debajo del umbral no se puede sostener ni refutar.",
                    tuple(per_brand))


def _pair_for(
    pts: List[Tuple[str, Optional[float], Optional[int]]],
    wave_code: Optional[str],
    wave_order: Sequence[str],
) -> Optional[Tuple[Tuple[Optional[float], Optional[int]],
                    Tuple[Optional[float], Optional[int]]]]:
    """El par (anterior, actual) que la conclusión está comentando."""
    if len(pts) < 2:
        return None
    order = {w: i for i, w in enumerate(wave_order)}
    pts = sorted(pts, key=lambda p: order.get(p[0], -1))
    if wave_code and wave_code in order:
        idx = next((i for i, p in enumerate(pts) if p[0] == wave_code), None)
        if idx is not None and idx > 0:
            prev, curr = pts[idx - 1], pts[idx]
            return (prev[1], prev[2]), (curr[1], curr[2])
        return None
    prev, curr = pts[-2], pts[-1]
    return (prev[1], prev[2]), (curr[1], curr[2])
