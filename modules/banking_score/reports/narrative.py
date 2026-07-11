"""Banking-specific narrative generation wrapper.

Delegates to ``shared.narrative.claude_engine.NarrativeEngine`` and adds
banking-domain context (section mapping, sub-component focus, etc.).
"""
import asyncio
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
    "executive_summary": "banking_summary",
    "solidez_financiera": "subcomponent_focus",
    "calidad_activos": "subcomponent_focus",
    "eficiencia_rentabilidad": "subcomponent_focus",
    "liquidez": "subcomponent_focus",
    "diversificacion": "subcomponent_focus",
    "risk_assessment": "banking_risk",
    "comparative": "banking_comparative",
    "recommendation": "banking_recommendation",
    "entorno_operativo": "banking_operating_env",
    "soporte_soberano": "banking_support_context",
    "trend_analysis": "trend_analysis",
    "sector_outlook": "sector_outlook",
}

# Plantillas de banking que van por la RUTA CEREBRO (axis="banking"): obtienen la Barra de
# Insight (conclusión-primero), la doctrina anti-jerga y el guardrail numérico. El resto
# (trend_analysis, sector_outlook) sigue en ruta legacy.
_CEREBRO_TEMPLATES = frozenset({
    "subcomponent_focus", "banking_summary", "banking_comparative",
    "banking_risk", "banking_recommendation", "banking_operating_env",
    "banking_support_context",
})

# Profundidad POR SECCIÓN (alineada con shared.products.section_mode), para que el deep dive
# PROFUNDICE en vez de re-narrar: el RIESGO forward es la capa profunda (deep → DEEP_DIRECTIVE
# vía cerebro, 700-1000 palabras de cadena causal); el CIERRE accionable es corto (standard,
# nunca inflado); el resto sigue el mode del nivel (detailed en niveles nombrados). Las
# secciones de ruta legacy con tablas verbosas (trend_analysis) suben a 'deep' SOLO por
# presupuesto de tokens (ahí 'deep' no agrega DEEP_DIRECTIVE).
_DEEP_SECTIONS = frozenset({"risk_assessment", "trend_analysis"})


def _section_mode(section: str, base_mode: str) -> str:
    """Mode de narrativa por sección: el cierre accionable corto, el riesgo profundo, el
    resto al mode pedido. Ver _DEEP_SECTIONS."""
    if section == "recommendation":
        return "standard"
    if section in _DEEP_SECTIONS:
        return "deep"
    return base_mode


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
    # Amplitud (Fase 4): trayectoria multi-período + percentil vs el sistema. Vienen en
    # el scoring_result (calculadas en snapshot con DB); pueden faltar en muestras/tests.
    traj = scoring_result.get("trayectorias") or {}
    pct = scoring_result.get("percentiles") or {}

    # Entorno Operativo (Fase 4): telón macro del BCRD (factores reales del contrato
    # compartido). Contexto propio — ni sub-componente ni panorama de la entidad: es el
    # entorno sistémico común, encuadrado para el perfil del banco.
    if section == "entorno_operativo":
        return {
            "entity_name": bank_name,
            "period": period,
            "rating_tier": scoring_result.get("rating_tier", "N/A"),
            "entorno_macro": scoring_result.get("entorno_macro", {}),
        }

    # Soporte y Techo Soberano (Fase 6): overlay de contexto estilo Fitch (soporte estatal,
    # importancia sistémica, techo soberano). Contexto propio — NO es el score standalone,
    # que se mantiene puro; se presenta como capa analítica separada.
    if section == "soporte_soberano":
        return {
            "entity_name": bank_name,
            "period": period,
            "rating_tier": scoring_result.get("rating_tier", "N/A"),
            "overall_score": scoring_result.get("overall_score", 0),
            "soporte_soberano": scoring_result.get("soporte_soberano", {}),
        }

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
        # Amplitud de la dimensión: la trayectoria del score del sub-componente, su
        # percentil vs el sistema, y —por indicador de la dimensión— su serie reciente
        # y su percentil. Da al cerebro la profundidad Fitch (evolución + posición
        # relativa) en vez de solo el corte actual.
        traj_sub = (traj.get("sub") or {}).get(sub_key)
        if traj_sub:
            ctx["trayectoria_sub_componente"] = traj_sub
        pct_sub = (pct.get("sub") or {}).get(sub_key)
        if pct_sub:
            ctx["percentil_sub_componente"] = pct_sub
        traj_ind = traj.get("indicators") or {}
        pct_ind = pct.get("indicators") or {}
        amplitud = {}
        for k in keys:
            if k not in ind:
                continue
            block = {}
            if traj_ind.get(k):
                block["trayectoria"] = traj_ind[k][-8:]
            if pct_ind.get(k):
                block["percentil"] = pct_ind[k]
            if block:
                amplitud[k] = block
        if amplitud:
            ctx["amplitud_indicadores"] = amplitud
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
        # Encuadre (Fase 3): mantiene la prosa consistente con las Limitaciones —
        # el score es fortaleza financiera standalone, no un rating de crédito.
        "encuadre": (
            "La calificación SDQ mide FORTALEZA FINANCIERA STANDALONE sobre dato público "
            "supervisado; NO es un rating de crédito ni mide probabilidad de incumplimiento, "
            "y no incorpora soporte soberano ni techo país. No la describas como rating "
            "crediticio ni la compares con las escalas de calificadoras internacionales."
        ),
    }
    # Amplitud a nivel de entidad: trayectoria del score global + de cada
    # sub-componente, y percentil vs el sistema (score global + sub-componentes). El
    # comparativo y el resumen ejecutivo leen posición relativa y evolución, no solo
    # el corte actual.
    if traj.get("overall"):
        ctx["trayectoria_score"] = traj["overall"]
    if traj.get("sub"):
        ctx["trayectoria_sub"] = traj["sub"]
    if pct.get("overall"):
        ctx["percentil_score"] = pct["overall"]
    if pct.get("sub"):
        ctx["percentil_sub"] = pct["sub"]
    # Sensibilidades (Fase 4): palancas al alza / riesgos a la baja con umbral en valor
    # crudo y delta al score global. El riesgo forward y el cierre accionable las citan
    # para dar umbrales concretos ("a qué nivel una señal pasa de vigilancia a acción").
    if scoring_result.get("sensibilidades"):
        ctx["sensibilidades"] = scoring_result["sensibilidades"]
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
        template = _SECTION_TO_TEMPLATE.get(section, "banking_summary")
        context = _build_section_context(
            section, bank_name, scoring_result, period, benchmarks,
        )

        # Use 'detailed' mode for full_rating to get longer outputs; las secciones de
        # panorama suben a 'deep' (4096) para no truncarse (ver _section_mode).
        base_mode = "detailed" if report_type == "full_rating" else "standard"
        mode = _section_mode(section, base_mode)

        # Ruta cerebro para las plantillas banking (resumen, comparativo, riesgo, decisión y
        # sub-componentes): Barra de Insight + doctrina anti-jerga + guardrail. El lector es
        # fijo (comité de crédito). trend_analysis/sector_outlook quedan en ruta legacy.
        cerebro = {"axis": "banking", "audience": "comite_credito"} \
            if template in _CEREBRO_TEMPLATES else {}

        result: NarrativeResult = await narrative_engine.generate(
            context=context,
            template=template,
            mode=mode,
            **cerebro,
        )
        narratives[section] = result.text

    return narratives


async def generate_named_narratives(
    sections: list,
    bank_name: str,
    scoring_result: Dict,
    period: str,
    benchmarks: Optional[Dict] = None,
    mode: str = "detailed",
) -> Dict[str, str]:
    """Genera narrativas para una lista EXPLÍCITA de secciones (driven por el manifiesto
    de nivel del producto), reutilizando el mapeo sección→template y el contexto
    enfocado existentes. No reemplaza ``generate_report_narratives`` (keyed por
    report_type); es la vía de la productización por niveles.
    """
    narratives: Dict[str, str] = {}
    # Una llamada IA por sección, generadas en PARALELO (asyncio.gather): antes era secuencial
    # (~15s × N secciones). El cliente Anthropic ya libera el event loop (asyncio.to_thread en
    # claude_engine); aquí solo falta lanzar las llamadas juntas. La construcción de contexto
    # (barata) sigue en el loop; solo el await del motor va al gather.
    pending: list = []   # (section, kwargs de generate)
    for section in sections:
        template = _SECTION_TO_TEMPLATE.get(section, "banking_summary")
        context = _build_section_context(section, bank_name, scoring_result, period, benchmarks)
        cerebro = {"axis": "banking", "audience": "comite_credito"} \
            if template in _CEREBRO_TEMPLATES else {}
        # Profundidad por sección: riesgo profundo, cierre corto, resto al mode pedido
        # (ver _section_mode).
        pending.append((section, dict(
            context=context, template=template, mode=_section_mode(section, mode), **cerebro,
        )))

    async def _gen(section: str, kwargs: Dict) -> tuple:
        result: NarrativeResult = await narrative_engine.generate(**kwargs)
        return section, result.text

    for section, text in await asyncio.gather(*(_gen(s, k) for s, k in pending)):
        narratives[section] = text
    return narratives
