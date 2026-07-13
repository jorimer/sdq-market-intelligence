"""Orquestador v2 — de la pregunta libre a la respuesta circunscrita al dato de los motores.

Flujo (§3.3 en su forma plena):
1. **Resuelve** qué eje(s) y qué entidad nombra la pregunta (``resolve``).
2. **Recibe el resultado de los motores** involucrados vía ``snapshot`` (``data_pull``) — dato
   REAL ya computado (rating, score, liquidez, percentil vs pares, alertas…).
3. **Descompone** la pregunta y recupera metodología con procedencia (``decompose``), fusionando
   la evidencia REAL del motor en las sub-preguntas que le corresponden.
4. **Gate de honestidad**: lo que ningún motor computa —una proyección/escenario a futuro— se
   declara brecha, no se rellena (``is_forward_looking``).
5. **Narrativa circunscrita**: el Cerebro ESCRIBE la respuesta usando SOLO el dato recibido, con
   el ``numeric_guard`` eliminando toda cifra no trazable (``narrate``). Si no hay motor de IA,
   degrada al ensamblado determinista.

La garantía de honestidad no depende del LLM: el gate, la procedencia y las brechas son
deterministas; el Cerebro solo pule la prosa sobre lo ya anclado.
"""
from __future__ import annotations

import asyncio
import logging
import time
from datetime import datetime, timezone
from typing import List, Optional, Tuple

from sqlalchemy.orm import Session

from shared.registry.signals import GAP, REAL, RUBRIC
from shared.research.assemble import assemble_report_sections, assemble_scoping_sections
from shared.research.data_pull import EnginePull, pull_axis, pull_entity
from shared.research.deep_report import build_synthesis_report
from shared.research.domain_router import merge_routing, route_domains

logger = logging.getLogger("sdq.research.orchestrator")

# Techo del enrutador semántico (una llamada LLM): si el Cerebro no responde a tiempo, el
# contexto curado ya sembrado por `resolve` basta — fiabilidad sobre exhaustividad.
_ROUTE_TIMEOUT_S = 12.0
from shared.research.decompose import (
    DEFAULT_MIN_ANCHOR_SCORE,
    decompose,
    is_forward_looking,
)
from shared.research.gate import DEFAULT_GAP_THRESHOLD, evaluate_gate
from shared.research.models import (
    GATE_SCOPING,
    DeclaredGap,
    ResearchAnswer,
    SubQuestion,
)
from shared.research.narrate import narrate_answer
from shared.research.resolve import AXIS_KEYWORDS, _norm, resolve_targets


async def _route_bounded(question: str, db: Optional[Session]) -> list:
    """`route_domains` con techo de latencia: al vencer, lista vacía (queda el curado)."""
    try:
        return await asyncio.wait_for(route_domains(question, db), _ROUTE_TIMEOUT_S)
    except asyncio.TimeoutError:
        logger.warning("route_domains excedió %.0fs; se sigue con el contexto curado.",
                       _ROUTE_TIMEOUT_S)
        return []


def _pull_known(db: Session, targets,
                axes: List[str]) -> Tuple[List[EnginePull], List[EnginePull]]:
    """Cosecha secuencial (una sesión, un thread) de entidades + ejes ya conocidos.
    Corre en un worker thread, en paralelo con el enrutador semántico (que no usa la DB)."""
    return ([pull_entity(db, e) for e in targets.entities],
            [pull_axis(db, ax) for ax in axes])


def _matches_pull(sq: SubQuestion, pull: EnginePull) -> bool:
    """¿La sub-pregunta corresponde a este motor? (nombra la entidad o el léxico del eje)."""
    q = _norm(sq.text)
    for tok in _norm(pull.entity_label).split():
        if len(tok) >= 4 and tok in q:
            return True
    return any(kw in q for kw in AXIS_KEYWORDS.get(pull.sector_key, ()))


def _merge_engine_evidence(sub_questions: List[SubQuestion], pulls: List[EnginePull]) -> None:
    """Antepone la evidencia REAL del motor a las sub-preguntas que le corresponden y las
    marca REAL. Si hay una sola sub-pregunta, recibe todos los motores vivos."""
    live = [p for p in pulls if p.ok and p.evidence]
    if not live:
        return
    for sq in sub_questions:
        matched = [p for p in live if _matches_pull(sq, p)]
        if not matched and len(sub_questions) == 1:
            matched = live
        for p in matched:
            sq.evidence = list(p.evidence) + sq.evidence
            if p.sector_key not in sq.axes:
                sq.axes.insert(0, p.sector_key)
        if matched:
            sq.state = REAL
            sq.note = ""


def _forward_gaps(question: str, sub_questions: List[SubQuestion],
                  live_pulls: List[EnginePull]) -> List[DeclaredGap]:
    """Si la pregunta pide una proyección/escenario a futuro y hay dato de motor (estado
    presente, no pronóstico), declara ese futuro como límite — sin rellenarlo."""
    if not is_forward_looking(question) or not live_pulls:
        return []
    return [DeclaredGap(
        sub_question=question,
        note=("La parte prospectiva (proyección/escenario a futuro) excede lo que los motores "
              "computan hoy: se reporta la posición ACTUAL con dato real (incl. señales de "
              "alerta temprana y sensibilidades), pero no un pronóstico —no se estima."),
        candidate_source=None,
    )]


def _collect_sources(sub_questions: List[SubQuestion]) -> List[str]:
    out: List[str] = []
    for want in (REAL, RUBRIC):
        for sq in sub_questions:
            for e in sq.evidence:
                if e.state == want and e.source and e.source not in out:
                    out.append(e.source)
    return out


def _collect_gaps(sub_questions: List[SubQuestion],
                  db: Optional[Session]) -> List[DeclaredGap]:
    gaps = [sq for sq in sub_questions if sq.state == GAP]
    if not gaps:
        return []
    candidates = _source_intel_candidates(db)
    return [DeclaredGap(sub_question=sq.text, note=sq.note, candidate_source=candidates)
            for sq in gaps]


def _source_intel_candidates(db: Optional[Session]) -> Optional[str]:
    if db is None:
        return None
    try:
        from shared.source_intel.models import SourceSuggestion
        rows = (db.query(SourceSuggestion)
                .filter(SourceSuggestion.status.in_(("proposed", "evaluating", "evaluated")))
                .limit(5).all())
        names = [r.title for r in rows if getattr(r, "title", None)]
        return "; ".join(names) if names else None
    except Exception:  # noqa: BLE001
        if db is not None:
            try:
                db.rollback()
            except Exception:  # noqa: BLE001
                pass
        return None


async def answer_question(question: str, db: Optional[Session] = None, *,
                          gap_threshold: float = DEFAULT_GAP_THRESHOLD,
                          per_q_k: int = 4,
                          min_anchor_score: float = DEFAULT_MIN_ANCHOR_SCORE,
                          narrate: bool = True) -> ResearchAnswer:
    """Responde una pregunta libre circunscrita al dato real de los motores + gate de honestidad."""
    t0 = time.monotonic()
    # 1-2. Resolver eje+entidad y recibir el resultado de los motores.
    targets = resolve_targets(question, db)
    axis_pulls: List[EnginePull] = []
    if narrate and db is not None:
        # Descomposición SEMÁNTICA (el Cerebro elige qué motores convoca) EN PARALELO con la
        # cosecha ya conocida: `route_domains` no toca la DB (invariante — si algún día la
        # usa, hay que revisar esto), así que la sesión la usa un solo worker thread a la
        # vez. Acotado con timeout: sin router a tiempo, el contexto curado basta.
        route_task = asyncio.ensure_future(_route_bounded(question, db))
        known_axes = list(dict.fromkeys(list(targets.axes) + list(targets.context)))
        pulls, axis_pulls = await asyncio.to_thread(_pull_known, db, targets, known_axes)
        merge_routing(targets, await route_task)
        # Dominios NUEVOS que el router agregó (no estaban en el mapa curado) → cosecharlos.
        extra = [ax for ax in list(targets.axes) + list(targets.context)
                 if ax not in known_axes]
        if extra:
            axis_pulls += await asyncio.to_thread(
                lambda: [pull_axis(db, ax) for ax in extra])
    else:
        pulls = [pull_entity(db, e) for e in targets.entities]
    # El ledger de honestidad cuenta TODA la cosecha viva — entidades Y ejes de sistema.
    # Hallazgo del piloto Fase 2: contarlo solo por-entidad hacía que una pregunta de
    # sistema (sin entidad) reportara "cobertura real 0%" con el dictamen lleno de dato
    # real, y —peor— NO declarara la brecha prospectiva ("próximos 2-3 años") porque
    # `_forward_gaps` exige cosecha viva. Entidades primero (evidencia más específica).
    live_pulls = [p for p in pulls if p.ok] + [p for p in axis_pulls if p.ok]
    t_pulls = time.monotonic()

    # 3. Descomponer + metodología, con la evidencia REAL del motor fusionada.
    sub_questions = decompose(question, db=db, per_q_k=per_q_k, min_anchor_score=min_anchor_score)
    _merge_engine_evidence(sub_questions, live_pulls)

    # 4. Gate de honestidad + brechas (incl. la prospectiva no-modelable).
    forward = _forward_gaps(question, sub_questions, live_pulls)
    gate, coverage_real, anchored_fraction = evaluate_gate(sub_questions, gap_threshold)
    sources = _collect_sources(sub_questions)
    gaps = _collect_gaps(sub_questions, db) + forward

    # 5. Reporte PROFUNDO: si se resolvió una entidad, reutiliza TODO el Deep Dive del
    #    producto + la capa de research (respuesta a la pregunta arriba). A US$7–10k el
    #    entregable debe superar un Deep Dive — no un resumen.
    deep = None
    section_order: List[str] = []
    if narrate and gate != GATE_SCOPING and (targets.entities or targets.context or live_pulls):
        # La cosecha YA se hizo arriba (entidades + ejes) — se pasa para no re-cosechar
        # (cada snapshot de entidad son varios queries: percentiles, concentración, pares).
        deep = await build_synthesis_report(question, db, targets, forward,
                                            pulls=pulls + axis_pulls)

    if deep is not None:
        sections = deep.sections
        section_order = deep.ordered_keys
        for s in deep.sources:
            if s not in sources:
                sources.insert(0, s)
    else:
        # Sin entidad profunda: ensamblado liviano (narrativa circunscrita o determinista).
        narrative = None
        if narrate and live_pulls:
            narrative = await narrate_answer(question, live_pulls,
                                             forward_gaps=[g.note for g in forward])
        if gate == GATE_SCOPING:
            sections = assemble_scoping_sections(question, sub_questions, sources, gaps,
                                                 coverage_real, anchored_fraction)
            section_order = ["resumen_scoping", "lo_que_si_se_puede", "lo_que_no_se_puede",
                             "que_cerraria_la_brecha", "metodologia", "fuentes"]
        else:
            sections = assemble_report_sections(question, sub_questions, sources, gaps,
                                                coverage_real, anchored_fraction,
                                                narrative=narrative)
            section_order = ["resumen_ejecutivo", "hallazgos", "metodologia", "fuentes",
                             "limitaciones"]
    section_order = [k for k in section_order if k in sections]
    t_end = time.monotonic()
    logger.info("research timings: route+pulls=%.1fs synthesis=%.1fs total=%.1fs (gate=%s)",
                t_pulls - t0, t_end - t_pulls, t_end - t0, gate)

    return ResearchAnswer(
        question=question, gate=gate, coverage_real=coverage_real,
        anchored_fraction=anchored_fraction, sub_questions=sub_questions,
        sections=sections, section_order=section_order, sources=sources, gaps=gaps,
        generated_at=datetime.now(timezone.utc).isoformat(), deep=deep,
    )
