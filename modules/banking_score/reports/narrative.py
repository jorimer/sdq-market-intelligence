"""Banking-specific narrative generation wrapper.

Delegates to ``shared.narrative.claude_engine.NarrativeEngine`` and adds
banking-domain context (section mapping, sub-component focus, etc.).
"""
from typing import Dict, Optional

from shared.narrative.claude_engine import NarrativeResult, narrative_engine
from modules.banking_score.scoring.weights import (
    SOLIDEZ_INDICATORS,
    CALIDAD_INDICATORS,
    EFICIENCIA_INDICATORS,
    LIQUIDEZ_INDICATORS,
    DIVERSIFICACION_INDICATORS,
)

# Indicators that belong to each sub-component (for focused per-dimension analysis).
_SUB_INDICATORS: Dict[str, list] = {
    "solidez": SOLIDEZ_INDICATORS,
    "calidad": CALIDAD_INDICATORS,
    "eficiencia": EFICIENCIA_INDICATORS,
    "liquidez": LIQUIDEZ_INDICATORS,
    "diversificacion": DIVERSIFICACION_INDICATORS,
}
_SUB_LABELS: Dict[str, str] = {
    "solidez": "Solidez Financiera",
    "calidad": "Calidad de Activos",
    "eficiencia": "Eficiencia y Rentabilidad",
    "liquidez": "Liquidez",
    "diversificacion": "Diversificación",
}

# Sections required per report type
REPORT_SECTIONS: Dict[str, list] = {
    "full_rating": [
        "executive_summary",
        "solidez_financiera",
        "calidad_activos",
        "eficiencia_rentabilidad",
        "liquidez",
        "diversificacion",
        "risk_assessment",
        "comparative",
        "recommendation",
    ],
    "scorecard": ["executive_summary", "recommendation"],
    "communique": ["executive_summary"],
    "datawatch": ["executive_summary", "trend_analysis"],
    "wire": ["executive_summary"],
    "criteria": ["risk_assessment"],
    "sector_outlook": ["sector_outlook"],
}

# Map each section to the NarrativeEngine template name
_SECTION_TO_TEMPLATE: Dict[str, str] = {
    "executive_summary": "executive_summary",
    "solidez_financiera": "subcomponent_focus",
    "calidad_activos": "subcomponent_focus",
    "eficiencia_rentabilidad": "subcomponent_focus",
    "liquidez": "subcomponent_focus",
    "diversificacion": "subcomponent_focus",
    "risk_assessment": "risk_assessment",
    "comparative": "comparative",
    "recommendation": "recommendation",
    "trend_analysis": "trend_analysis",
    "sector_outlook": "sector_outlook",
}

# Sub-component key lookup for focused sections
_SUB_COMPONENT_MAP: Dict[str, str] = {
    "solidez_financiera": "solidez",
    "calidad_activos": "calidad",
    "eficiencia_rentabilidad": "eficiencia",
    "liquidez": "liquidez",
    "diversificacion": "diversificacion",
}


def _build_section_context(
    section: str,
    bank_name: str,
    scoring_result: Dict,
    period: str,
    benchmarks: Optional[Dict] = None,
) -> Dict:
    """Build the context dict that gets serialized into the Claude prompt."""
    all_indicators = scoring_result.get("indicators", {})
    sub_key = _SUB_COMPONENT_MAP.get(section)

    # Sub-component sections: a TIGHT context with only this dimension's indicators,
    # its driver/drag and its peer stats — so the model analyses the dimension in
    # depth instead of re-deriving the whole bank (which read as repetitive).
    if sub_key:
        keys = _SUB_INDICATORS.get(sub_key, [])
        ind = {k: all_indicators[k] for k in keys if k in all_indicators}
        scored = {
            k: v for k, v in ind.items()
            if isinstance(v, dict) and v.get("available", True) and v.get("score") is not None
        }
        driver = max(scored, key=lambda k: scored[k]["score"], default=None)
        drag = min(scored, key=lambda k: scored[k]["score"], default=None)
        ctx: Dict = {
            "entity_name": bank_name,
            "period": period,
            "rating_tier": scoring_result.get("rating_tier", "N/A"),
            "sub_componente": _SUB_LABELS.get(sub_key, sub_key),
            "score_sub_componente": scoring_result.get("sub_components", {}).get(sub_key, 0),
            "indicadores": ind,
            "impulsor": driver,
            "lastre": drag,
        }
        if benchmarks and isinstance(benchmarks, dict):
            sub_bench = benchmarks.get(sub_key) or benchmarks.get(section)
            if sub_bench:
                ctx["pares"] = sub_bench
        return ctx

    # Overview sections (executive summary, comparative, recommendation…) keep the
    # full picture.
    ctx = {
        "entity_name": bank_name,
        "period": period,
        "overall_score": scoring_result.get("overall_score", 0),
        "rating_tier": scoring_result.get("rating_tier", "N/A"),
        "sub_components": scoring_result.get("sub_components", {}),
        "indicators": all_indicators,
    }
    if benchmarks:
        ctx["benchmarks"] = benchmarks
    return ctx


async def generate_report_narratives(
    report_type: str,
    bank_name: str,
    scoring_result: Dict,
    period: str,
    benchmarks: Optional[Dict] = None,
) -> Dict[str, str]:
    """Generate all narrative sections required for *report_type*.

    Returns ``{section_key: narrative_text}``.
    """
    sections = REPORT_SECTIONS.get(report_type, ["executive_summary"])
    narratives: Dict[str, str] = {}

    for section in sections:
        template = _SECTION_TO_TEMPLATE.get(section, "executive_summary")
        context = _build_section_context(
            section, bank_name, scoring_result, period, benchmarks,
        )

        # Use 'detailed' mode for full_rating to get longer outputs
        mode = "detailed" if report_type == "full_rating" else "standard"

        # Cerebro route only for the in-scope banking template; el reporte tiene un
        # lector fijo (comité de crédito). El resto de secciones queda en ruta legacy.
        cerebro = {"axis": "banking", "audience": "comite_credito"} \
            if template == "subcomponent_focus" else {}

        result: NarrativeResult = await narrative_engine.generate(
            context=context,
            template=template,
            mode=mode,
            **cerebro,
        )
        narratives[section] = result.text

    return narratives
