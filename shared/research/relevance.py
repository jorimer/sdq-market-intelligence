"""Verificación de relevancia tema-pasaje — A4.2 del gate de honestidad.

docs/SPEC_GATE_HONESTIDAD_Y_FUENTES_DGII.md §A.4 A4.2. El fix estructural del bug: antes de
aceptar RUBRIC para una sub-pregunta anclada SOLO en doctrina/metodología (texto libre que
cruzó el umbral por vocabulario compartido, no por relevancia), un paso barato pregunta al
Cerebro sí/no: "¿alguno de estos pasajes es método aplicable a esta sub-pregunta?". Si no,
la sub-pregunta cae a GAP —brecha honesta— en vez de un "100% con ancla" falso.

Garantías (misma doctrina anti-fabricación que el resto del motor, mismo patrón defensivo
que ``domain_router``):
- Solo puede DEGRADAR (RUBRIC→GAP), nunca al revés — la honestidad no depende del LLM.
- Fallback conservador: sin Cerebro (sin API key), sin presupuesto, error de API o
  respuesta inválida → se trata como NO relevante → GAP (nunca al revés).
- No toca la DB; las llamadas se agrupan (``asyncio.gather``) sin el patrón concurrente
  DB-en-thread que causó el P0 del router.
"""
from __future__ import annotations

import asyncio
import json
import logging
import re
from typing import List, Optional

from shared.registry.signals import GAP, REAL, RUBRIC
from shared.research.models import Evidence, SubQuestion

logger = logging.getLogger("sdq.research.relevance")

# Kinds de texto libre cuya RUBRIC hay que verificar. Un pasaje ``registry`` ATADO A UN EJE
# (lleva ``sector_key`` en su procedencia) es temático por construcción y NO se re-verifica.
_TEXT_KINDS = ("doctrine", "methodology", "bulletin")

# Registry EXTERNO no atado a un eje del catálogo (padrón DGII, ref ``dgii/…``): es dato REAL,
# pero se empareja por puro solape léxico del sustantivo del vertical (p.ej. "hoteles"), sin la
# garantía temática del registry con ``sector_key``. Por eso un conteo de contribuyentes puede
# anclar una pregunta sobre rentabilidad/empleo/precios que NO responde. Se verifica igual que
# el texto libre —aunque sea REAL— para no reintroducir el "ancla falsa" que cerró A4.2.
_UNBOUND_REF_PREFIXES = ("dgii/",)
_MAX_PASSAGES = 4       # pasajes de contexto por sub-pregunta (recorte anti-costo)
_PASSAGE_CHARS = 500    # recorte por pasaje

_SYSTEM = (
    "Sos el verificador de relevancia del motor de research de SDQ (inteligencia financiera "
    "de República Dominicana). Dada una PREGUNTA y unos PASAJES (doctrina/metodología propia, o "
    "un conteo estadístico), decidís si AL MENOS UNO es un método, marco, criterio, definición o "
    "DATO que responda esa pregunta concreta. Que compartan vocabulario NO basta: '¿cuántas "
    "cadenas de comida rápida operan?' NO se responde con la metodología de formatos de salida de "
    "un reporte ni con la escala de un índice de riesgo-país; y un CONTEO de contribuyentes de un "
    "sector NO responde una pregunta sobre rentabilidad, empleo, precios o desempeño de ese "
    "sector. Sé estricto. Respondé SÓLO un objeto JSON, sin texto alrededor."
)
_USER = (
    "PREGUNTA:\n{question}\n\nPASAJES:\n{passages}\n\n"
    'Devolvé JSON con esta forma EXACTA: {{"aplicable": true}} o {{"aplicable": false}}.'
)


def _is_unbound(e: Evidence) -> bool:
    """¿Evidencia `registry` externa NO atada a un eje (padrón DGII)? Ancla por solape léxico."""
    return e.kind == "registry" and (getattr(e, "ref", "") or "").startswith(_UNBOUND_REF_PREFIXES)


def _to_verify(e: Evidence) -> bool:
    """Evidencia anclada por solape léxico (texto libre o registry externo) → se verifica."""
    return e.kind in _TEXT_KINDS or _is_unbound(e)


def _best_state(evidence: list) -> str:
    """Mejor ancla que soporta la evidencia restante: real > rúbrica > brecha."""
    if any(e.state == REAL for e in evidence):
        return REAL
    if any(e.state == RUBRIC for e in evidence):
        return RUBRIC
    return GAP


def _needs_check(sq: SubQuestion) -> bool:
    """¿Esta sub-pregunta ancla por solape léxico sin garantía temática (el vector del bug)?

    - Registry externo (DGII): se verifica aunque sea REAL —no está atado a un eje—.
    - Texto libre (doctrina/metodología): se verifica solo si ancló RUBRIC y no hay un
      registry ATADO a eje que ya la exima (comportamiento original de A4.2)."""
    if any(_is_unbound(e) for e in sq.evidence):
        return sq.state in (REAL, RUBRIC)
    if sq.state != RUBRIC:
        return False
    if any(e.kind == "registry" for e in sq.evidence):
        return False
    return any(e.kind in _TEXT_KINDS for e in sq.evidence)


def _extract_bool(raw: str) -> Optional[bool]:
    """``aplicable`` del primer objeto JSON de la respuesta (tolera fences/prosa)."""
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
    val = obj.get("aplicable") if isinstance(obj, dict) else None
    return bool(val) if isinstance(val, bool) else None


async def is_method_applicable(question: str, passages: List[str],
                               lang: str = "es") -> bool:
    """¿Alguno de *passages* es método aplicable a *question*? Fail-safe: ``False`` ante
    cualquier problema (sin cliente, sin presupuesto, error, JSON inválido) — el fallback
    conservador es NO relevante, para que la sub-pregunta caiga a GAP, nunca a RUBRIC."""
    if not passages:
        return False
    from shared.config.settings import settings
    from shared.llm.budget import budget_allows, record_usage
    from shared.narrative.claude_engine import narrative_engine

    client = narrative_engine._get_client()
    if client is None or not budget_allows():
        return False  # sin Cerebro/presupuesto → conservador (GAP)

    body = "\n\n".join(f"- {p[:_PASSAGE_CHARS]}" for p in passages[:_MAX_PASSAGES])
    user = _USER.format(question=(question or "").strip(), passages=body)
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
    except Exception as e:  # noqa: BLE001 — cualquier fallo del API → conservador (GAP)
        logger.warning("is_method_applicable: fallo del Cerebro (%s); se asume NO aplicable.", e)
        return False

    verdict = _extract_bool(raw)
    return verdict is True  # None (inválido) → conservador → GAP


async def verify_rubric_relevance(question: str, sub_questions: List[SubQuestion]) -> None:
    """Degrada RUBRIC→GAP (mutación in-situ) para las sub-preguntas ancladas SOLO en texto
    libre que el Cerebro juzga NO aplicable a la pregunta. Nunca lanza: cualquier fallo del
    conjunto deja el estado determinista (A4.1/A4.3) tal cual."""
    from shared.config.settings import settings

    if not getattr(settings, "RESEARCH_RELEVANCE_CHECK", True):
        return
    targets = [sq for sq in sub_questions if _needs_check(sq)]
    if not targets:
        return
    # `return_exceptions=True` + aislar por-check: si UN check falla (import, cliente,
    # presupuesto), su excepción se trata como NO aplicable (→ GAP, el fallback conservador),
    # sin abandonar el lote ni dejar rúbricas permisivas por un fallo aislado.
    try:
        verdicts = await asyncio.gather(*[
            is_method_applicable(sq.text, [e.text for e in sq.evidence if _to_verify(e)])
            for sq in targets], return_exceptions=True)
    except Exception as e:  # noqa: BLE001 — el pase completo jamás rompe la request
        logger.warning("verify_rubric_relevance falló en bloque (%s); estado determinista.", e)
        return
    for sq, verdict in zip(targets, verdicts):
        applicable = verdict is True  # Exception o False → NO aplicable → GAP (conservador)
        if not applicable:
            # Se descarta SOLO la evidencia anclada por solape léxico (texto libre + registry
            # externo DGII) que el Cerebro juzgó no pertinente —si no, `_collect_sources`
            # seguiría citando la fuente irrelevante en "Fuentes"—. Se preservan las anclas de
            # registry ATADAS a un eje (dato real temático), y el estado se recomputa con lo
            # que quede: un GAP no cita evidencia; una sub-pregunta con otra ancla válida la
            # conserva (coherente con el §4).
            sq.evidence = [e for e in sq.evidence if not _to_verify(e)]
            sq.state = _best_state(sq.evidence)
            if not sq.evidence:
                sq.note = ("La evidencia recuperada comparte vocabulario pero no es método "
                           "aplicable ni dato pertinente a esta sub-pregunta (verificado): "
                           "brecha declarada, no se ancla en evidencia irrelevante.")
