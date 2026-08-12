"""El marco de comparación de una ola: contra la anterior y contra la de un año atrás.

Un tracker se lee habitualmente contra la ola anterior, y esa lectura confunde dos cosas
distintas: el movimiento del trimestre y el del ciclo. Una caída de mayo a agosto puede
ser estacionalidad del verano y no deterioro; solo la comparación con la misma época del
año anterior las separa.

**Las olas reales son irregulares.** El calendario efectivo del encargo —septiembre 2018,
julio 2019, febrero y septiembre 2020, septiembre 2021, julio 2022, julio 2023, mayo 2024,
mayo/agosto/noviembre 2025, marzo y junio 2026— no tiene una ola exactamente doce meses
antes de cada ola. Forzar el calce inventaría una comparación; descartarla por no ser
exacta la perdería casi siempre. La regla (decisión del dueño): **la ola más próxima a los
doce meses atrás, dentro de una tolerancia declarada, y SIEMPRE con la distancia real a la
vista**. Si ninguna cae en la tolerancia, la comparación se declara no disponible.

Que la distancia viaje con la comparación no es cosmético: «contra mayo de 2025, trece
meses atrás» y «contra junio de 2025» sostienen conclusiones distintas sobre
estacionalidad, y el lector necesita saber cuál tiene delante.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import date
from typing import Any, Dict, List, Optional, Sequence

logger = logging.getLogger("sdq.brand_intel.frame")

#: Tolerancia alrededor de los doce meses. Tres meses admite un calendario que se corre
#: de trimestre —el caso real— y excluye una ola de otra estación, que es lo que la
#: comparación interanual justamente intenta evitar.
YEAR_TOLERANCE_MONTHS = 3


def _months_between(a: date, b: date) -> int:
    """Meses calendario entre dos fechas (positivo si ``a`` es posterior)."""
    return (a.year - b.year) * 12 + (a.month - b.month)


@dataclass
class WaveRef:
    code: str
    label: str
    period: Optional[date]

    def as_dict(self) -> Dict[str, Any]:
        return {"code": self.code, "label": self.label,
                "period": self.period.isoformat() if self.period else None}


def resolve_frame(waves: Sequence[Any], target_code: Optional[str] = None) -> Dict[str, Any]:
    """El marco de la ola objetivo: ella, la anterior y la de un año atrás.

    ``waves`` son las olas CON DATO, en orden cronológico. ``target_code`` por defecto es
    la última. Cada base ausente se declara con su motivo en vez de omitirse.
    """
    serie = [WaveRef(str(w.code), str(w.label or w.code),
                     getattr(w, "period_date", None)) for w in waves]
    if not serie:
        return {"available": False, "reason": "El encargo no tiene olas con dato."}

    codes = [w.code for w in serie]
    if target_code and target_code not in codes:
        return {"available": False,
                "reason": (f"La ola '{target_code}' no tiene dato en el encargo. "
                           f"Olas disponibles: {', '.join(codes)}.")}
    idx = codes.index(target_code) if target_code else len(serie) - 1
    target = serie[idx]

    previous = serie[idx - 1] if idx > 0 else None
    prev_gap = (_months_between(target.period, previous.period)
                if previous and target.period and previous.period else None)

    # Ola de un año atrás: la más próxima a −12 meses dentro de la tolerancia, buscada
    # solo entre las ANTERIORES a la objetivo (una ola posterior no es «un año atrás»).
    year_ago: Optional[WaveRef] = None
    year_gap: Optional[int] = None
    year_reason: Optional[str] = None
    if target.period is None:
        year_reason = "La ola objetivo no tiene fecha de período declarada."
    else:
        candidatas = [
            (abs(_months_between(target.period, w.period) - 12), w,
             _months_between(target.period, w.period))
            for w in serie[:idx] if w.period
        ]
        dentro = [c for c in candidatas if c[0] <= YEAR_TOLERANCE_MONTHS]
        if dentro:
            dentro.sort(key=lambda c: (c[0], -c[2]))
            _d, year_ago, year_gap = dentro[0]
        elif candidatas:
            mas_cerca = min(candidatas, key=lambda c: c[0])
            year_reason = (
                f"Ninguna ola cae a doce meses de la objetivo con tolerancia de "
                f"{YEAR_TOLERANCE_MONTHS} meses; la más próxima es "
                f"«{mas_cerca[1].label}», a {mas_cerca[2]} meses. La comparación "
                "interanual no se publica: a esa distancia mezclaría estaciones "
                "distintas.")
        else:
            year_reason = "No hay olas anteriores con fecha declarada."

    out: Dict[str, Any] = {
        "available": True,
        "target": target.as_dict(),
        "previous": previous.as_dict() if previous else None,
        "previous_gap_months": prev_gap,
        "year_ago": year_ago.as_dict() if year_ago else None,
        "year_ago_gap_months": year_gap,
        "year_ago_reason": year_reason,
        "series": [w.as_dict() for w in serie],
        "is_latest": idx == len(serie) - 1,
    }
    if previous is None:
        out["previous_reason"] = ("La ola objetivo es la primera con dato: no hay ola "
                                 "anterior contra la que comparar.")
    notas: List[str] = []
    if previous and prev_gap is not None:
        notas.append(f"Ola anterior: «{previous.label}», {prev_gap} mes(es) atrás.")
    if year_ago and year_gap is not None:
        notas.append(
            f"Ola de referencia interanual: «{year_ago.label}», {year_gap} meses atrás"
            + (" — no son doce meses exactos, y la distancia real se declara porque "
               "condiciona la lectura de estacionalidad."
               if year_gap != 12 else "."))
    if year_reason:
        notas.append(year_reason)
    out["note"] = " ".join(notas)
    return out
