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
    out = []
    for e in sq.evidence[:limit]:
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

    limitaciones_parts = [
        _coverage_line(coverage_real, anchored_fraction),
    ]
    if gaps:
        limitaciones_parts.append("\nBrechas declaradas (no contestadas con dato):")
        for g in gaps:
            extra = f" Fuente candidata en evaluación: {g.candidate_source}." if g.candidate_source else ""
            limitaciones_parts.append(f"- {g.sub_question}.{extra}")
    if any(sq.state == RUBRIC for sq in sub_questions):
        limitaciones_parts.append(
            "\nParte del ancla es rúbrica declarada (juicio de casa), no dato observado; "
            "sube a dato real cuando la fuente correspondiente se integre.")
    limitaciones = "\n".join(limitaciones_parts)

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
                              coverage_real: float,
                              anchored_fraction: float) -> Dict[str, str]:
    """Scoping report: la brecha supera el umbral → se declara honestamente qué se puede
    y no contestar hoy, y qué cerraría la brecha. NO se entrega un informe con apariencia
    de completo."""
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
    lo_que_si = ("\n\n".join(lo_que_si_parts)
                 if lo_que_si_parts else "_Ninguna línea alcanzó ancla con evidencia hoy._")

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
    }
    contexto = _related_context_section(sub_questions)
    if contexto:
        out["contexto_relacionado"] = contexto
    return out
