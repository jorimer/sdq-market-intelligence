"""Banking-specific narrative generation wrapper.

Delegates to ``shared.narrative.claude_engine.NarrativeEngine`` and adds
banking-domain context (section mapping, sub-component focus, etc.).
"""
from typing import Dict, Optional

from shared.narrative.claude_engine import NarrativeResult, narrative_engine

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
    "solidez_financiera": "risk_assessment",
    "calidad_activos": "risk_assessment",
    "eficiencia_rentabilidad": "risk_assessment",
    "liquidez": "risk_assessment",
    "diversificacion": "risk_assessment",
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
    ctx: Dict = {
        "entity_name": bank_name,
        "period": period,
        "overall_score": scoring_result.get("overall_score", 0),
        "rating_tier": scoring_result.get("rating_tier", "N/A"),
        "sub_components": scoring_result.get("sub_components", {}),
        "indicators": scoring_result.get("indicators", {}),
    }

    if benchmarks:
        ctx["benchmarks"] = benchmarks

    # Narrow the focus for sub-component-specific sections
    sub_key = _SUB_COMPONENT_MAP.get(section)
    if sub_key:
        ctx["focus_area"] = sub_key
        ctx["focus_score"] = scoring_result.get("sub_components", {}).get(
            sub_key, 0
        )

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

        result: NarrativeResult = await narrative_engine.generate(
            context=context,
            template=template,
            mode=mode,
        )
        narratives[section] = result.text

    return narratives
