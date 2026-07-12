"""Narrativa circunscrita — el Cerebro redacta la respuesta desde el dato de los motores.

Orquestador v2 (§3.3 llevado a su forma plena). Toma el ``payload`` real que devolvió un
motor y le pide al Cerebro (``narrative_engine.generate`` con el template ``research_answer``)
que ESCRIBA la respuesta a la pregunta usando SOLO esas cifras. El ``numeric_guard`` de la
ruta cerebro elimina cualquier número que no trace al 'datos' recibido — es la garantía
mecánica de "insight circunscrito a lo recibido". Si no hay motor Anthropic (fallback
estático) o el eje no tiene doctrina, degrada con gracia (devuelve ``None`` → el orquestador
usa el ensamblado determinista).
"""
from __future__ import annotations

import logging
from typing import List, Optional

from shared.research.data_pull import EnginePull

logger = logging.getLogger("sdq.research.narrate")

# Catálogo sector_key → axis de la doctrina del Cerebro (AXIS_DOCTRINE). Los que no mapean
# (p.ej. insurance) caen a la ruta legacy de generate() con gracia (sin persona de eje).
_CEREBRO_AXIS = {
    "banking": "banking",
    "macro": "macro_monitor",
    "monetary_policy": "macro_monitor",
    "trade": "trade_intel",
    "tourism": "tourism_intel",
    "free_zones": "free_zones_intel",
    "energy": "energy_intel",
    "telecom": "telecom_intel",
    "construction": "construction_intel",
    "agribusiness": "sector_intel",
    "economic_structure": "economic_structure",
    "esg": "esg_climate",
    "pension": "pension_intel",
}


async def narrate_synthesis(question: str, pulls: List[EnginePull],
                            *, forward_gaps: Optional[List[str]] = None,
                            lang: str = "es") -> Optional[str]:
    """Síntesis CROSS-DOMINIO: integra el dato de VARIOS motores (entidad + contexto macro/
    monetario/…) alrededor de la pregunta. Es el núcleo del research tema-primero. ``None`` si
    no hay dato o el Cerebro no está disponible."""
    live = [p for p in pulls if p.ok and p.payload]
    if not live:
        return None
    from shared.narrative.claude_engine import narrative_engine

    # Persona del eje primario (el primer motor con entidad, o el primero); el guard verifica
    # las cifras contra TODO el contexto multi-dominio, no solo ese eje.
    axis = _CEREBRO_AXIS.get(live[0].sector_key)
    context = {
        "pregunta": question,
        "dominios": [
            {"dominio": p.entity_label, "eje": p.sector_key, "fuente": p.source,
             "procedencia": "real", "resultado_del_motor": p.payload}
            for p in live
        ],
    }
    if forward_gaps:
        context["fuera_de_alcance"] = forward_gaps
    try:
        res = await narrative_engine.generate(
            context=context, template="research_synthesis", mode="deep",
            lang=lang, axis=axis, audience=None)
    except Exception as e:  # noqa: BLE001
        logger.warning("narrate_synthesis falló: %s", e)
        return None
    if not res or not res.text or res.model_used == "static_fallback":
        return None
    return res.text.strip()


async def narrate_answer(question: str, pulls: List[EnginePull],
                         *, forward_gaps: Optional[List[str]] = None,
                         lang: str = "es") -> Optional[str]:
    """Redacta la respuesta a *question* circunscrita al dato de *pulls*. ``None`` si no hay
    dato de motor o el Cerebro no está disponible (→ fallback determinista del orquestador)."""
    live = [p for p in pulls if p.ok and p.payload]
    if not live:
        return None

    from shared.narrative.claude_engine import narrative_engine

    primary = live[0]
    axis = _CEREBRO_AXIS.get(primary.sector_key)  # None → generate() usa ruta legacy
    context = {
        "pregunta": question,
        "datos": [
            {"entidad": p.entity_label, "eje": p.sector_key, "fuente": p.source,
             "procedencia": "real", "resultado_del_motor": p.payload}
            for p in live
        ],
    }
    if forward_gaps:
        context["fuera_de_alcance"] = forward_gaps

    try:
        # mode="deep": respuesta extensa y multi-faceta (es un entregable de US$7-10k, no un
        # resumen). El DEEP_DIRECTIVE del motor gana sobre el tope de palabras del template.
        res = await narrative_engine.generate(
            context=context, template="research_answer", mode="deep",
            lang=lang, axis=axis, audience=None,
        )
    except Exception as e:  # noqa: BLE001 — cualquier fallo del motor → determinista
        logger.warning("narrate_answer falló: %s", e)
        return None

    if not res or not res.text or res.model_used == "static_fallback":
        return None
    return res.text.strip()
