"""Mezcla de primas por ramo, y el TIPO DE COMPAÑÍA derivado de ella.

El catálogo regulatorio del SIS no trae un campo "tipo de compañía", y el módulo tampoco lo
modelaba. Pero la mezcla de ramos sí está persistida por compañía y ejercicio
(``InsuranceSeries.dimension``), así que el tipo se **deriva del negocio real** en vez de
declararse a mano — mismo criterio que en el resto de la casa: las relaciones se computan.

Para qué hace falta: el ancla de Ejecución en seguros es el breakeven del combined ratio
(100%), que es un hecho económico **para daños**. Salud y personas operan con loss ratios
estructuralmente distintos —en RD las ARS tienen piso regulatorio de gasto en siniestros—
así que un combined de 104% puede ser su operación normal y no un mal desempeño. Sin saber
la mezcla no se puede distinguir "ejecuta mal" de "es otro negocio", que es exactamente el
error que en banca se corrigió calculando los cortes por tipo de entidad.
"""
from typing import Any, Dict, List, Optional, Sequence

from modules.insurance_intel.external.audited_excel_extractor import (
    RAMOS_GENERALES,
    RAMOS_PERSONAS,
)

# La taxonomía NO se re-escribe acá: se deriva del extractor, que es su única fuente. Si
# mañana el catálogo suma un ramo, esto lo hereda sin tocar nada.
RAMOS_DE_PERSONAS = frozenset(RAMOS_PERSONAS)
RAMOS_DE_DANOS = frozenset(RAMOS_GENERALES.values())

# "salud" es el ramo con el piso regulatorio de siniestralidad; se sigue aparte del resto de
# personas porque es el que más desplaza el combined ratio.
RAMO_SALUD = "salud"

# Por debajo de este peso la compañía no tiene suficiente negocio de personas como para que
# la mezcla explique su combined ratio; por encima del alto, difícilmente sea comparable con
# una de daños. Los cortes son de JUICIO, no derivados — se declaran como tales.
UMBRAL_MIXTA = 0.25
UMBRAL_PERSONAS = 0.60


def clasificar(peso_personas: Optional[float]) -> Optional[str]:
    """Tipo derivado del peso de personas en la prima. ``None`` si no hay mezcla."""
    if peso_personas is None:
        return None
    if peso_personas >= UMBRAL_PERSONAS:
        return "personas"
    if peso_personas >= UMBRAL_MIXTA:
        return "mixta"
    return "danos"


def mezcla_de_una(filas: Sequence[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    """Mezcla de una compañía a partir de sus filas ``{dimension, value}`` de primas.

    Devuelve ``None`` si no hay ningún ramo con prima: sin desglose no se inventa una mezcla,
    y en particular no se asume "daños" por defecto — sería clasificar por ausencia de dato.
    """
    por_ramo: Dict[str, float] = {}
    for f in filas:
        dim, val = f.get("dimension"), f.get("value")
        if not dim or val is None:
            continue
        try:
            v = float(val)
        except (TypeError, ValueError):
            continue
        if v > 0:  # primas negativas (ajustes de cierre) no forman parte de una mezcla
            por_ramo[dim] = por_ramo.get(dim, 0.0) + v

    total = sum(por_ramo.values())
    if total <= 0:
        return None

    personas = sum(v for r, v in por_ramo.items() if r in RAMOS_DE_PERSONAS)
    danos = sum(v for r, v in por_ramo.items() if r in RAMOS_DE_DANOS)
    salud = por_ramo.get(RAMO_SALUD, 0.0)
    # Un ramo que no esté en ninguna de las dos familias es taxonomía nueva: se reporta como
    # no clasificado en vez de asignarse en silencio a la que más convenga.
    sin_clasificar = total - personas - danos

    peso_personas = personas / total
    return {
        "peso_personas": round(peso_personas, 4),
        "peso_danos": round(danos / total, 4),
        "peso_salud": round(salud / total, 4),
        "peso_sin_clasificar": round(max(0.0, sin_clasificar) / total, 4),
        "primas_totales": round(total, 2),
        "ramos": sorted(por_ramo, key=lambda r: -por_ramo[r]),
        "tipo": clasificar(peso_personas),
    }


def agrupar_por_entidad(filas: Sequence[Dict[str, Any]]) -> Dict[str, List[Dict[str, Any]]]:
    """Agrupa filas de series por ``entity_slug`` preservando el resto de campos."""
    out: Dict[str, List[Dict[str, Any]]] = {}
    for f in filas:
        slug = f.get("entity_slug")
        if slug:
            out.setdefault(slug, []).append(f)
    return out
