"""Política ÚNICA de profundidad por sección para las narrativas de producto.

El problema que resuelve: cada producto generaba TODA sección de un tier con un solo
``mode`` (standard/detailed/deep). En ``deep_dive`` eso anexaba el ``DEEP_DIRECTIVE`` a
cada sección y la inflaba a 700-1000 palabras → el deep dive REPETÍA el mismo análisis
varias veces en vez de profundizar. (Ver el rediseño de ``economic_structure``.)

La regla correcta, una sola fuente de verdad para los 12 productos:

* ``pulse``   → ``standard`` (lectura abierta, breve).
* ``insight`` → ``detailed`` (una pasada ejecutiva con razonamiento).
* ``deep_dive``:
    - el CIERRE accionable (``recommendation`` / ``decision``) → ``standard``: corto y
      filoso, NUNCA inflado (es lo que más repetía).
    - UNA sección analítica lleva la capa de profundidad → ``deep`` (700-1000 palabras,
      cadena causal + escenario). Por defecto, la primera sección analítica; un producto
      puede designar otra (p. ej. ``economic_structure`` usa ``mechanism``), o ``None``
      para no profundizar ninguna (p. ej. banking, cuya profundidad viene de su amplitud
      de sub-componentes).
    - el resto de las secciones analíticas → ``detailed``: desarrolladas, no infladas.

``limitations`` se sirve estática en cada producto y nunca llega al motor; no se modela aquí.
"""
from __future__ import annotations

from typing import Optional, Sequence

from shared.products.tiers import ProductTier

# Secciones de CIERRE accionable: corto siempre, nunca se inflan.
SHORT_CLOSE_SECTIONS = frozenset({"recommendation", "decision"})
# Secciones estáticas (no pasan por el motor de narrativa).
STATIC_SECTIONS = frozenset({"limitations"})

# Centinela: "profundiza la PRIMERA sección analítica" (default). Distinto de ``None``,
# que significa "no profundices ninguna" (todas las analíticas en ``detailed``).
_FIRST_ANALYTICAL = object()


def section_mode(
    tier: ProductTier,
    section: str,
    sections: Sequence[str],
    *,
    deep_section: object = _FIRST_ANALYTICAL,
) -> str:
    """Devuelve el ``mode`` de narrativa para *section* dentro de *tier*.

    *sections* es la tupla completa de secciones del tier (para localizar la primera
    analítica). *deep_section* designa qué sección lleva la profundidad en ``deep_dive``:
    omitido → la primera analítica; un nombre → esa; ``None`` → ninguna.
    """
    if tier == ProductTier.pulse:
        return "standard"
    if tier != ProductTier.deep_dive:
        return "detailed"  # insight (y cualquier tier intermedio)

    # deep_dive ───────────────────────────────────────────────────────────────
    if section in SHORT_CLOSE_SECTIONS:
        return "standard"

    target: Optional[str]
    if deep_section is _FIRST_ANALYTICAL:
        analytical = [s for s in sections
                      if s not in SHORT_CLOSE_SECTIONS and s not in STATIC_SECTIONS]
        target = analytical[0] if analytical else None
    else:
        target = deep_section  # type: ignore[assignment]

    return "deep" if section == target else "detailed"
