"""Fase 5 — integración a producción: la respuesta del motor → entregable de marca.

docs/SPEC_MOTOR_RESEARCH_CUSTOM.md §5 Fase 5. El motor acelera el SKU DD Full/Deep Dive:
el analista corre una pregunta y obtiene un BORRADOR anclado a procedencia con la misma
anatomía y marca del catálogo, sobre el que construye el DD final. Reutiliza el pipeline
de render existente (`shared/products/render.render_product_pdf`) — PDF y Word, portada
de marca, disclaimer, encabezado corrido — sin duplicar el chrome (§7: consume el
REPORT_STANDARD, no lo duplica).

Marca de agua "BORRADOR" por defecto: el entregable es un acelerador interno, no un DD
firmado. El analista lo revisa y lo eleva a definitivo. Un scoping report se entrega tal
cual (es honesto por diseño), sin marca de borrador si el llamador lo desea.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Dict, Optional

from shared.research.export import ordered_sections
from shared.research.models import GATE_SCOPING, ResearchAnswer

# Títulos legibles de las secciones del motor (para el render numerado).
_SECTION_TITLES: Dict[str, str] = {
    "resumen_ejecutivo": "Resumen ejecutivo",
    "hallazgos": "Hallazgos",
    "metodologia": "Metodología",
    "fuentes": "Fuentes",
    "limitaciones": "Limitaciones",
    "resumen_scoping": "Alcance",
    "lo_que_si_se_puede": "Lo que se puede contestar hoy",
    "lo_que_no_se_puede": "Lo que no se puede contestar hoy",
    "que_cerraria_la_brecha": "Qué cerraría la brecha",
}

_DEFAULT_WATERMARK = "BORRADOR · motor de research"


def _subject(question: str, limit: int = 90) -> str:
    q = " ".join((question or "").split())
    return (q[:limit] + "…") if len(q) > limit else q


def render_deliverable(answer: ResearchAnswer, *, fmt: str = "pdf",
                       output_dir: Optional[str] = None,
                       watermark: Optional[str] = _DEFAULT_WATERMARK) -> str:
    """Renderiza la respuesta como entregable de marca (PDF o Word) y devuelve el path.

    Reusa ``render_product_pdf`` (mismo motor branded del catálogo). Las secciones se
    pasan como ``narratives`` en el orden canónico según el gate (informe o scoping)."""
    from shared.products.render import render_product_pdf

    sections = ordered_sections(answer)  # [(título, markdown)] en orden canónico
    # narratives: clave → texto, en orden. Reconstruimos las claves desde el orden.
    order_keys = [k for k, _ in _iter_answer_keys(answer)]
    narratives: Dict[str, str] = {}
    titles: Dict[str, str] = {}
    for key in order_keys:
        if key in answer.sections:
            narratives[key] = answer.sections[key]
            titles[key] = _SECTION_TITLES.get(key, key.replace("_", " ").title())

    kind = ("SDQ Research — Scoping Report" if answer.gate == GATE_SCOPING
            else "SDQ Research — Informe a medida")
    headline = (f"{answer.coverage_real:.0%} dato real · "
                f"{answer.anchored_fraction:.0%} con ancla")
    period = (answer.generated_at[:10] if answer.generated_at
              else datetime.now(timezone.utc).strftime("%Y-%m-%d"))

    return render_product_pdf(
        sector_key="research_custom", display_name=_subject(answer.question),
        title=kind, period=period, narratives=narratives, section_titles=titles,
        headline=headline, subtitle="Motor de Research Custom",
        watermark=watermark, fmt=fmt, output_dir=output_dir,
    )


def _iter_answer_keys(answer: ResearchAnswer):
    """Orden canónico de claves de sección según el gate (espeja export.ordered_sections
    pero devuelve las CLAVES, para alimentar el render por-narrativa)."""
    if answer.gate == GATE_SCOPING:
        keys = ["resumen_scoping", "lo_que_si_se_puede", "lo_que_no_se_puede",
                "que_cerraria_la_brecha", "metodologia", "fuentes"]
    else:
        keys = ["resumen_ejecutivo", "hallazgos", "metodologia", "fuentes", "limitaciones"]
    return [(k, None) for k in keys]
