"""Verificación de pertinencia de entidad — el candado del Cerebro sobre el matcher léxico.

Caso que motiva este módulo: la pregunta "¿dónde se podría ubicar una sucursal nueva de
McDonald's?" resolvió la entidad "Citibank N.A. Sucursal República Dominicana" por la
palabra "sucursal", y el informe completo (portada, rating, pares) quedó anclado a un banco
que no venía al caso. La corroboración léxica (``resolve._AMBIGUOUS_TOKENS``) mata esa
clase de match; este módulo cubre la cola larga que ninguna lista curada anticipa: para
cada entidad resuelta con match DÉBIL (``ResolvedEntity.weak``), un paso barato pregunta
al Cerebro sí/no: "¿la pregunta trata de esta entidad?".

Garantías (mismo patrón defensivo que ``relevance``/``domain_router``):
- Solo puede DESCARTAR entidades, nunca agregar.
- La dirección fail-safe es CONSERVAR: sin Cerebro (sin API key), sin presupuesto, error de
  API o respuesta inválida → la entidad se mantiene. El piso determinista del matcher no
  depende del LLM (a diferencia de ``relevance``, donde lo conservador es degradar a GAP:
  acá descartar por un fallo técnico rompería toda pregunta legítima por entidad).
- Un descarte recomputa el ``Targets`` completo (``finalize_targets``): el contexto que la
  entidad falsa sembró (monetario/macro de banking) no sobrevive al descarte.
"""
from __future__ import annotations

import asyncio
import json
import logging
import re
from typing import List, Optional

from shared.research.resolve import ResolvedEntity, Targets, detect_axes, finalize_targets

logger = logging.getLogger("sdq.research.entity_check")

_SYSTEM = (
    "Sos el verificador de entidades del motor de research de SDQ (inteligencia financiera "
    "de República Dominicana). Dada una PREGUNTA libre de un comprador y una ENTIDAD del "
    "catálogo (con su dominio), decidís si la pregunta TRATA de esa entidad —su desempeño, "
    "riesgo, posición o comparación—. Que el nombre legal comparta una palabra con la "
    "pregunta NO basta: una pregunta sobre abrir una sucursal de una cadena de comida "
    "rápida NO trata del banco 'Citibank N.A. Sucursal República Dominicana' aunque "
    "comparta la palabra 'sucursal'; una pregunta sobre el motor de la economía NO trata de "
    "'Motor Crédito'. Sé estricto. Respondé SÓLO un objeto JSON, sin texto alrededor."
)
_USER = (
    "PREGUNTA:\n{question}\n\nENTIDAD:\n{label} (dominio: {sector})\n\n"
    'Devolvé JSON con esta forma EXACTA: {{"sobre_entidad": true}} o {{"sobre_entidad": false}}.'
)


def _extract_bool(raw: str) -> Optional[bool]:
    """``sobre_entidad`` del primer objeto JSON de la respuesta (tolera fences/prosa)."""
    if not raw:
        return None
    raw = raw.strip()
    if raw.startswith("```"):
        raw = re.sub(r"^```(?:json)?", "", raw).rsplit("```", 1)[0].strip()
    s, e = raw.find("{"), raw.rfind("}")
    if s == -1 or e <= s:
        return None
    try:
        obj = json.loads(raw[s:e + 1])
    except (json.JSONDecodeError, ValueError):
        return None
    val = obj.get("sobre_entidad") if isinstance(obj, dict) else None
    return bool(val) if isinstance(val, bool) else None


async def _is_about_entity(question: str, entity: ResolvedEntity) -> Optional[bool]:
    """¿La pregunta trata de *entity*? ``None`` = sin veredicto (sin cliente/presupuesto/
    error/JSON inválido) — el llamador conserva la entidad en ese caso."""
    from shared.config.settings import settings
    from shared.llm.budget import budget_allows, record_usage
    from shared.narrative.claude_engine import narrative_engine

    client = narrative_engine._get_client()
    if client is None or not budget_allows():
        return None  # sin Cerebro/presupuesto → sin veredicto → se conserva
    user = _USER.format(question=(question or "").strip(),
                        label=entity.label, sector=entity.sector_key)
    try:
        async with narrative_engine._get_sem():
            resp = await asyncio.to_thread(
                client.messages.create,
                model=settings.ANTHROPIC_MODEL, max_tokens=64, temperature=0.0,
                system=_SYSTEM, messages=[{"role": "user", "content": user}])
        raw = "".join(getattr(b, "text", "") for b in (resp.content or []))
        usage = getattr(resp, "usage", None)
        if usage is not None:
            record_usage(settings.ANTHROPIC_MODEL,
                         getattr(usage, "input_tokens", 0) or 0,
                         getattr(usage, "output_tokens", 0) or 0)
    except Exception as e:  # noqa: BLE001 — cualquier fallo del API → sin veredicto
        logger.warning("_is_about_entity: fallo del Cerebro (%s); se conserva la entidad.", e)
        return None
    return _extract_bool(raw)


async def verify_entity_pertinence(question: str, targets: Targets) -> None:
    """Descarta (mutación in-situ) las entidades de match DÉBIL que el Cerebro juzga NO
    pertinentes a la pregunta. Nunca lanza; solo un ``false`` explícito descarta. Si algo
    se descartó, el ``Targets`` se recomputa para que el contexto sembrado por la entidad
    espuria no sobreviva."""
    from shared.config.settings import settings

    if not getattr(settings, "RESEARCH_ENTITY_CHECK", True):
        return
    weak = [e for e in targets.entities if e.weak]
    if not weak:
        return
    try:
        verdicts = await asyncio.gather(*[_is_about_entity(question, e) for e in weak],
                                        return_exceptions=True)
    except Exception as e:  # noqa: BLE001 — el pase completo jamás rompe la request
        logger.warning("verify_entity_pertinence falló en bloque (%s); se conserva todo.", e)
        return
    dropped = {id(ent) for ent, v in zip(weak, verdicts) if v is False}
    if not dropped:
        return
    kept: List[ResolvedEntity] = [ent for ent in targets.entities if id(ent) not in dropped]
    for ent, v in zip(weak, verdicts):
        if v is False:
            logger.info("entity_check: descartada '%s' (match débil por '%s') — la pregunta "
                        "no trata de esa entidad.", ent.label, ent.matched_on)
    rebuilt = finalize_targets(question, detect_axes(question), kept)
    targets.entities = rebuilt.entities
    targets.axes = rebuilt.axes
    targets.context = rebuilt.context
