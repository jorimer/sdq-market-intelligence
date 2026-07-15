"""Ensamblado de la salida con la anatomía del REPORT_STANDARD (§3.4).

Dos formas: informe completo (gate REPORT) o scoping report honesto (gate SCOPING).
Ambos se pueblan dinámicamente por pregunta, no por template fijo, y reutilizan las
secciones canónicas —Resumen, Hallazgos, Metodología, Fuentes, Limitaciones— con
Metodología/Fuentes/Limitaciones derivadas de la procedencia (no redactadas a mano).

Determinista y en español neutro (tono advisory, sin anglicismos casuales — regla
transversal del catálogo). Cada hallazgo cita la fuente de su evidencia; nada material
queda sin ancla.
"""
from __future__ import annotations

from typing import Dict, List, Optional

from shared.registry.signals import REAL, RUBRIC
from shared.research.models import DeclaredGap, SubQuestion

_STATE_LABEL = {REAL: "dato real", RUBRIC: "rúbrica declarada", "gap": "brecha declarada"}


def _evidence_lines(sq: SubQuestion, limit: int = 3) -> str:
    """Líneas de evidencia citadas de una sub-pregunta, garantizando AL MENOS una por cada
    FUENTE distinta presente.

    Una truncación plana ``sq.evidence[:limit]`` descartaba ejes legítimamente matcheados
    cuando una pregunta agrupa 2+ sectores en una sola sub-pregunta: el merge
    (``_merge_engine_evidence``) antepone la evidencia de cada motor, así el motor procesado al
    final queda al frente; si trae ``limit`` evidencias propias, copa todos los cupos y los
    demás motores (aunque anclen el estado) no aportan ninguna línea visible. Se agrupa por
    ``source`` y se recorre en round-robin (una de cada fuente por ronda) → el slice captura al
    menos una de cada una. El presupuesto total se expande a ``n_fuentes`` cuando excede
    ``limit`` (nunca se cae una fuente); con una sola fuente el comportamiento es el de antes."""
    groups: Dict[str, List] = {}
    for e in sq.evidence:
        groups.setdefault(e.source, []).append(e)
    if not groups:
        return ""
    budget = max(limit, len(groups))  # ≥1 por fuente: el presupuesto nunca es menor a n_fuentes
    picked: List = []
    round_idx = 0
    while len(picked) < budget and any(round_idx < len(evs) for evs in groups.values()):
        for evs in groups.values():
            if round_idx < len(evs):
                picked.append(evs[round_idx])
                if len(picked) >= budget:
                    break
        round_idx += 1
    out = []
    for e in picked:
        etiqueta = _STATE_LABEL.get(e.state, e.state)
        out.append(f"  - _{e.source}_ ({etiqueta}): {e.text.strip()[:280]}")
    return "\n".join(out)


def _coverage_line(coverage_real: float, anchored_fraction: float) -> str:
    return (f"Cobertura de la respuesta: **{coverage_real:.0%}** anclada a dato real, "
            f"**{anchored_fraction:.0%}** con ancla declarada (dato real o rúbrica). "
            f"El resto se declara como brecha explícita.")


def _related_context_section(sub_questions: List[SubQuestion]) -> str:
    """Dato REAL recuperado que NO responde ninguna sub-pregunta (el chequeo de relevancia lo
    descartó como ancla) pero es contexto adyacente. Deduplica por (fuente, ref). ``""`` si no
    hay. NO cuenta para la cobertura: es contexto, no respuesta —lo dice el encabezado."""
    seen = set()
    lines: List[str] = []
    for sq in sub_questions:
        for e in sq.related_context:
            key = (e.source, e.ref or e.text[:60])
            if key in seen:
                continue
            seen.add(key)
            lines.append(f"- _{e.source}_: {e.text.strip()[:400]}")
    if not lines:
        return ""
    return ("_Dato real que SDQ tiene sobre el tema, mostrado como CONTEXTO: no responde "
            "directamente lo consultado, pero acota el terreno. No cuenta para la cobertura._"
            "\n\n" + "\n".join(lines))


def _limitaciones_lines(gaps: List[DeclaredGap], coverage_real: float,
                        anchored_fraction: float, sub_questions: List[SubQuestion]) -> str:
    """Sección 'Limitaciones' COMPARTIDA por el informe completo y el scoping report: cobertura +
    brechas declaradas + aviso de rúbrica. Determinista, desde los mismos parámetros que ambos
    ensamblados ya reciben. Extraída para no duplicar la lógica (Hallazgo 9: el scoping no la
    tenía pese a tener todos los insumos)."""
    parts = [_coverage_line(coverage_real, anchored_fraction)]
    if gaps:
        parts.append("\nBrechas declaradas (no contestadas con dato):")
        for g in gaps:
            extra = f" Fuente candidata en evaluación: {g.candidate_source}." if g.candidate_source else ""
            parts.append(f"- {g.sub_question}.{extra}")
    if any(sq.state == RUBRIC for sq in sub_questions):
        parts.append(
            "\nParte del ancla es rúbrica declarada (juicio de casa), no dato observado; "
            "sube a dato real cuando la fuente correspondiente se integre.")
    return "\n".join(parts)


def assemble_report_sections(question: str, sub_questions: List[SubQuestion],
                             sources: List[str], gaps: List[DeclaredGap],
                             coverage_real: float, anchored_fraction: float,
                             narrative: Optional[str] = None) -> Dict[str, str]:
    """Informe completo: cobertura suficiente para responder con ancla mayoritaria.

    Si *narrative* viene dado (el Cerebro escribió la respuesta circunscrita al dato de los
    motores), es el cuerpo del resumen ejecutivo; los hallazgos quedan como respaldo con la
    evidencia citada. Sin narrativa, el resumen es el determinista (cobertura + estructura)."""
    anchored = [sq for sq in sub_questions if sq.anchored]
    gapped = [sq for sq in sub_questions if not sq.anchored]

    if narrative:
        resumen = (
            f"**Pregunta:** {question}\n\n{narrative}\n\n"
            f"_{_coverage_line(coverage_real, anchored_fraction)}_")
    else:
        resumen = (
            f"**Pregunta:** {question}\n\n"
            f"{_coverage_line(coverage_real, anchored_fraction)}\n\n"
            f"Se descompuso la consulta en {len(sub_questions)} línea(s) de análisis; "
            f"{len(anchored)} con evidencia de procedencia clara y {len(gapped)} sin ancla "
            f"(declaradas como brecha). Las conclusiones de abajo se sostienen solo sobre "
            f"la evidencia citada — ninguna afirmación se completa con conocimiento general.")

    hallazgos_parts: List[str] = []
    for i, sq in enumerate(anchored, 1):
        ejes = f" · ejes: {', '.join(sq.axes)}" if sq.axes else ""
        hallazgos_parts.append(
            f"### {i}. {sq.text}\n"
            f"_Ancla: {_STATE_LABEL.get(sq.state, sq.state)}{ejes}_\n\n"
            f"Evidencia:\n{_evidence_lines(sq)}")
    hallazgos = "\n\n".join(hallazgos_parts) or "_Sin hallazgos anclados._"

    metodologia = (
        "La respuesta se produjo recuperando evidencia con procedencia sobre el corpus "
        "propio de SDQ (doctrina versionada y metodología) y el Data Registry vivo (qué "
        "dato real existe hoy por eje/variable). No se consultó la web abierta ni se "
        "ingirieron fuentes externas en vivo. Cada sub-pregunta se ancló al mejor estado "
        "que su evidencia soporta (dato real, rúbrica declarada o brecha); lo que no tuvo "
        "evidencia se declaró brecha, sin rellenar con conocimiento del modelo.")

    fuentes = ("\n".join(f"- {s}" for s in sources)
               if sources else "_Sin fuentes con dato real en esta respuesta._")

    limitaciones = _limitaciones_lines(gaps, coverage_real, anchored_fraction, sub_questions)

    out = {
        "resumen_ejecutivo": resumen,
        "hallazgos": hallazgos,
        "metodologia": metodologia,
        "fuentes": fuentes,
        "limitaciones": limitaciones,
    }
    contexto = _related_context_section(sub_questions)
    if contexto:
        out["contexto_relacionado"] = contexto
    return out


def assemble_scoping_sections(question: str, sub_questions: List[SubQuestion],
                              sources: List[str], gaps: List[DeclaredGap],
                              coverage_real: float, anchored_fraction: float,
                              narrative: Optional[str] = None) -> Dict[str, str]:
    """Scoping report: la brecha supera el umbral → se declara honestamente qué se puede
    y no contestar hoy, y qué cerraría la brecha. NO se entrega un informe con apariencia
    de completo.

    Si *narrative* viene dado (el Cerebro redactó la respuesta circunscrita al dato de los
    motores con el template ``research_answer``, diseñado para declarar brecha), es la antesala
    de 'Lo que se puede contestar hoy' — el framing de síntesis antes de los bullets de
    evidencia (Hallazgo 8: esa narrativa se calculaba y se descartaba en el scoping)."""
    anchored = [sq for sq in sub_questions if sq.anchored]
    gapped = [sq for sq in sub_questions if not sq.anchored]

    resumen = (
        f"**Pregunta:** {question}\n\n"
        f"**Alcance honesto (no informe completo).** Con el corpus y los datos "
        f"disponibles hoy, la cobertura con ancla declarada es de solo "
        f"**{anchored_fraction:.0%}** ({coverage_real:.0%} con dato real) — por debajo "
        f"del umbral para emitir un informe completo. En lugar de rellenar los huecos, "
        f"SDQ entrega este alcance: qué se puede contestar con evidencia hoy, qué no, y "
        f"qué fuente cerraría cada brecha.")

    lo_que_si_parts: List[str] = []
    for i, sq in enumerate(anchored, 1):
        lo_que_si_parts.append(
            f"### {i}. {sq.text}\n_Ancla: {_STATE_LABEL.get(sq.state, sq.state)}_\n\n"
            f"Evidencia:\n{_evidence_lines(sq)}")
    lo_que_si_body = ("\n\n".join(lo_que_si_parts)
                      if lo_que_si_parts else "_Ninguna línea alcanzó ancla con evidencia hoy._")
    # Antesala de síntesis (Cerebro), si vino: framing antes de los bullets de evidencia.
    lo_que_si = (f"{narrative.strip()}\n\n{lo_que_si_body}"
                 if narrative and narrative.strip() else lo_que_si_body)

    lo_que_no = ("\n".join(f"- {sq.text}" for sq in gapped)
                 if gapped else "_Sin brechas: todo lo consultado tiene ancla._")

    cierre_parts: List[str] = []
    if gaps and any(g.candidate_source for g in gaps):
        cierre_parts.append("Fuentes candidatas en evaluación (tablero de Inteligencia de "
                            "Fuentes):")
        vistos = set()
        for g in gaps:
            if g.candidate_source and g.candidate_source not in vistos:
                vistos.add(g.candidate_source)
                cierre_parts.append(f"- {g.candidate_source}")
    cierre_parts.append(
        "\nLas fuentes nuevas necesarias siguen el flujo de Inteligencia de Fuentes "
        "(propuesta → evaluación → gate humano → integración). Este motor no scrapea "
        "fuentes en vivo dentro de una respuesta al cliente.")
    que_cerraria = "\n".join(cierre_parts)

    metodologia = (
        "Recuperación con procedencia sobre el corpus propio (doctrina + metodología) y "
        "el Data Registry vivo. Sin web abierta ni ingesta externa en vivo. El gate de "
        "publicación exige que la mayoría del cuerpo tenga ancla (dato real o rúbrica "
        "declarada); al no cumplirse, se entrega alcance en vez de informe.")

    fuentes = ("\n".join(f"- {s}" for s in sources)
               if sources else "_Sin fuentes con dato real disponibles para esta consulta hoy._")

    out = {
        "resumen_scoping": resumen,
        "lo_que_si_se_puede": lo_que_si,
        "lo_que_no_se_puede": lo_que_no,
        "que_cerraria_la_brecha": que_cerraria,
        "metodologia": metodologia,
        "fuentes": fuentes,
        # Hallazgo 9: el scoping SÍ debe declarar sus limitaciones (cobertura + brechas +
        # aviso de rúbrica) — tiene todos los insumos; misma lógica que el informe completo.
        "limitaciones": _limitaciones_lines(gaps, coverage_real, anchored_fraction, sub_questions),
    }
    contexto = _related_context_section(sub_questions)
    if contexto:
        out["contexto_relacionado"] = contexto
    return out
