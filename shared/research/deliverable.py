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
    "contexto_relacionado": "Contexto relacionado",
}

_DEFAULT_WATERMARK = "BORRADOR · motor de research"


def _subject(question: str, limit: int = 480) -> str:
    """Título de portada: la pregunta COMPLETA (el renderer escala el cuerpo según el largo,
    ver `_cover`). Solo se recorta —en frontera de palabra— si es desmesuradamente larga, para
    no desbordar la portada; el texto íntegro va igual en el cuerpo (sección 'Pregunta')."""
    q = " ".join((question or "").split())
    if len(q) <= limit:
        return q
    cut = q[:limit].rsplit(" ", 1)[0]  # no cortar la última palabra
    return cut.rstrip(" ,;:") + "…"


def render_deliverable(answer: ResearchAnswer, *, fmt: str = "pdf",
                       output_dir: Optional[str] = None,
                       watermark: Optional[str] = _DEFAULT_WATERMARK) -> str:
    """Renderiza la respuesta como entregable de marca (PDF o Word) y devuelve el path.

    Reusa ``render_product_pdf`` (mismo motor branded del catálogo). Si la respuesta trae un
    reporte PROFUNDO (Deep Dive + capa de research), renderiza todas sus secciones en orden
    con gráficos/tablas del dato real; si no, las secciones livianas."""
    from shared.products.render import render_product_pdf

    # Orden de secciones: el resuelto por el orquestador (profundo o liviano).
    order = answer.section_order or [k for k, _ in _iter_answer_keys(answer)]
    deep = answer.deep
    title_map = dict(_SECTION_TITLES)
    if deep is not None and getattr(deep, "titles", None):
        title_map.update(deep.titles)

    narratives: Dict[str, str] = {}
    titles: Dict[str, str] = {}
    for key in order:
        if key in answer.sections:
            narratives[key] = answer.sections[key]
            titles[key] = title_map.get(key, key.replace("_", " ").title())

    kind = ("SDQ Research — Scoping Report" if answer.gate == GATE_SCOPING
            else "SDQ Research — Informe a medida")
    if deep is not None and getattr(deep, "headline", ""):
        headline = f"{deep.entity_label} · {deep.headline}"
    else:
        # ANIDADOS, no aditivos: el de dato real está DENTRO del anclado. "67% dato real ·
        # 67% con ancla" se lee como 67+67 y deja al lector buscando el resto. Se muestra el
        # total anclado y su composición sólo cuando hay rúbrica; si coinciden, se dice que
        # todo es dato real, que es la lectura fuerte y la que se estaba perdiendo.
        _rub = answer.anchored_fraction - answer.coverage_real
        headline = (f"{answer.anchored_fraction:.0%} con ancla · todo dato real"
                    if _rub < 0.005 else
                    f"{answer.anchored_fraction:.0%} con ancla "
                    f"({answer.coverage_real:.0%} dato real + {_rub:.0%} rúbrica)")
    period = ((deep.period if deep is not None and getattr(deep, "period", None) else None)
              or (answer.generated_at[:10] if answer.generated_at
                  else datetime.now(timezone.utc).strftime("%Y-%m-%d")))
    charts = getattr(deep, "charts", None) if deep is not None else None
    tables = getattr(deep, "tables", None) if deep is not None else None

    return render_product_pdf(
        sector_key="research_custom", display_name=_subject(answer.question),
        title=kind, period=str(period), narratives=narratives, section_titles=titles,
        tables=tables, charts=charts, headline=headline,
        subtitle="Motor de Research Custom",
        watermark=watermark, fmt=fmt, output_dir=output_dir,
    )


def _iter_answer_keys(answer: ResearchAnswer):
    """Orden canónico de claves de sección según el gate (espeja export.ordered_sections
    pero devuelve las CLAVES, para alimentar el render por-narrativa)."""
    if answer.gate == GATE_SCOPING:
        keys = ["resumen_scoping", "lo_que_si_se_puede", "lo_que_no_se_puede",
                "que_cerraria_la_brecha", "metodologia", "fuentes", "limitaciones"]
    else:
        keys = ["resumen_ejecutivo", "hallazgos", "metodologia", "fuentes", "limitaciones"]
    return [(k, None) for k in keys]
