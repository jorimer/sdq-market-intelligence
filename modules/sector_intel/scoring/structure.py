"""Estructura Sectorial de la Economía — vista agregada de los 17 sectores.

Función pura sobre dato real del BCRD (PIB por sectores de origen): el peso de cada
sector en el Valor Agregado (``sector_size``, %) y su crecimiento real interanual
(``sector_growth``, %). A diferencia del IAI (atractividad por sector) o del ranking de
exportaciones (valor exportado por capítulo), esto mide la **importancia económica real**
y, sobre todo, la **contribución al crecimiento** = peso × crecimiento — la lente que
responde "¿qué sectores mueven la economía?".

  * Un sector grande que se contrae (p. ej. construcción ~13% del PIB pero −1.8%) RESTA.
  * Uno mediano que crece rápido (financiero ~4.6% y +7.5%) APORTA.

La suma de las contribuciones ≈ crecimiento del Valor Agregado total. Producto descriptivo
(no es un índice 0-100): no fabrica un score sintético; expone la estructura real.
"""
from typing import Dict, List, Optional


def _contribution(weight: Optional[float], growth: Optional[float]) -> Optional[float]:
    """Aporte del sector al crecimiento del VAB total, en puntos porcentuales:
    ``peso% × crecimiento% / 100``. ``None`` si falta peso o crecimiento."""
    if weight is None or growth is None:
        return None
    return round(weight * growth / 100.0, 3)


def _hhi(weights: List[float]) -> Optional[float]:
    """HHI (0..10000) de la concentración estructural por peso de sector."""
    total = sum(weights)
    if total <= 0:
        return None
    return round(sum((w / total) ** 2 for w in weights) * 10000, 1)


def compute_economic_structure(
    sectors: Dict[str, Dict[str, Optional[float]]],
    names: Optional[Dict[str, str]] = None,
) -> Dict:
    """Estructura económica agregada desde ``{slug: {sector_size, sector_growth}}``.

    Devuelve los sectores rankeados por peso, los motores y lastres del crecimiento
    (por contribución), el crecimiento agregado del VAB y la concentración estructural.
    Honesto con la cobertura: solo cuenta sectores con dato; nunca fabrica cifras.
    """
    names = names or {}
    rows: List[Dict] = []
    weights_present: List[float] = []
    total_growth = 0.0
    contrib_weight = 0.0  # Σ pesos con peso Y crecimiento (cobertura de la contribución)

    for slug, vars_ in sectors.items():
        weight = vars_.get("sector_size")
        growth = vars_.get("sector_growth")
        contribution = _contribution(weight, growth)
        rows.append({
            "slug": slug,
            # clave "sector" (no "name"): es una categoría económica pública, no una firma —
            # el sensor de anonimización del Pulse prohíbe la clave "name".
            "sector": names.get(slug, slug),
            "weight": round(weight, 3) if weight is not None else None,
            "growth": round(growth, 2) if growth is not None else None,
            "contribution": contribution,
        })
        if weight is not None:
            weights_present.append(weight)
        if contribution is not None:
            total_growth += contribution
            contrib_weight += weight  # weight is not None when contribution is not None

    total_growth = round(total_growth, 2)
    # Cuota de cada motor sobre el crecimiento total (solo si el total es no nulo).
    for r in rows:
        c = r["contribution"]
        r["contribution_share"] = (round(c / total_growth, 4)
                                   if c is not None and total_growth not in (0, 0.0) else None)

    by_weight = sorted([r for r in rows if r["weight"] is not None],
                       key=lambda r: r["weight"], reverse=True)
    drivers = sorted([r for r in rows if r["contribution"] is not None and r["contribution"] > 0],
                     key=lambda r: r["contribution"], reverse=True)
    drags = sorted([r for r in rows if r["contribution"] is not None and r["contribution"] < 0],
                   key=lambda r: r["contribution"])

    coverage = round(sum(weights_present) / 100.0, 4) if weights_present else 0.0
    return {
        "total_va_growth": total_growth,
        "coverage": coverage,                      # fracción del VAB con dato de peso
        "contribution_coverage": round(contrib_weight / 100.0, 4),
        "concentration_hhi": _hhi(weights_present),
        "n_sectors": len(rows),
        "sectors": by_weight,                      # ranking por peso (estructura)
        "drivers": drivers,                        # motores del crecimiento (aporte +)
        "drags": drags,                            # lastres (aporte −)
        "top_weight": by_weight[0] if by_weight else None,
        "top_driver": drivers[0] if drivers else None,
        "top_drag": drags[0] if drags else None,
    }
