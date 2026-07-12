"""Exportación de la respuesta a documento — costura de integración a DD (Fase 5).

docs/SPEC_MOTOR_RESEARCH_CUSTOM.md §3.4/§5 Fase 5 y §7: este motor CONSUME la anatomía
del REPORT_STANDARD, no la duplica. Aquí se ordena la salida en las secciones canónicas
(portada → resumen → hallazgos → metodología → fuentes → limitaciones) y se produce un
markdown listo para entregar en el piloto y, cuando el ``ReportSpec`` del REPORT_STANDARD
§10 esté implementado, para alimentarlo directamente (mismo contenido, otro renderer).

El orden de secciones difiere entre informe completo y scoping report — ambos honestos.
"""
from __future__ import annotations

from typing import List, Tuple

from shared.research.models import GATE_SCOPING, ResearchAnswer

# Orden canónico de secciones por tipo de salida (rótulo visible → clave interna).
_REPORT_ORDER: List[Tuple[str, str]] = [
    ("Resumen ejecutivo", "resumen_ejecutivo"),
    ("Hallazgos", "hallazgos"),
    ("Metodología", "metodologia"),
    ("Fuentes", "fuentes"),
    ("Limitaciones", "limitaciones"),
]
_SCOPING_ORDER: List[Tuple[str, str]] = [
    ("Alcance", "resumen_scoping"),
    ("Lo que se puede contestar hoy", "lo_que_si_se_puede"),
    ("Lo que no se puede contestar hoy", "lo_que_no_se_puede"),
    ("Qué cerraría la brecha", "que_cerraria_la_brecha"),
    ("Metodología", "metodologia"),
    ("Fuentes", "fuentes"),
]


def ordered_sections(answer: ResearchAnswer) -> List[Tuple[str, str]]:
    """``[(título, markdown)]`` en el orden canónico según el gate. Omite secciones
    ausentes (resiliente)."""
    order = _SCOPING_ORDER if answer.gate == GATE_SCOPING else _REPORT_ORDER
    return [(title, answer.sections[key]) for title, key in order
            if key in answer.sections]


def to_markdown(answer: ResearchAnswer) -> str:
    """Documento markdown completo de la respuesta, con la anatomía del REPORT_STANDARD."""
    kind = ("Scoping Report — alcance honesto" if answer.gate == GATE_SCOPING
            else "Market Intelligence Report — respuesta a medida")
    out: List[str] = [
        "# SDQ · Market Intelligence",
        f"## {kind}\n",
        f"_Cobertura: {answer.coverage_real:.0%} dato real · "
        f"{answer.anchored_fraction:.0%} con ancla declarada · "
        f"generado {answer.generated_at[:10]}_\n",
    ]
    for title, body in ordered_sections(answer):
        out.append(f"## {title}\n")
        out.append(body.strip() + "\n")
    return "\n".join(out)
