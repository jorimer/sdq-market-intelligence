"""Compact AI context for the pension-system (SIPEN) narrative.

The narrative engine receives a SMALL, pre-digested context — the system headline
(rentabilidad CCI/SDP, comisiones) and the per-AFP rentabilidad dispersion (leader,
laggard, spread) — never the full series set, so prompts stay cheap and focused.
Mirrors :mod:`trade_intel.ai_context`. Source: SIPEN (dato real).
"""
from typing import Any, Dict, List


def pension_entity_context(rating: Dict[str, Any], peers: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Compact context for one AFP's ISA narrative (template ``pension_entity``).

    *rating* is the AFP's ISA result (overall, band, coverage, dimensions); *peers* is
    the full ranking so the narrative can place the AFP against its peers without
    recomputing. Solvency travels as a named gap, never a fabricated figure.
    """
    dims = rating.get("dimensions") or []
    ranked = [r for r in peers if r.get("overall_score") is not None]
    rank = next((i + 1 for i, r in enumerate(ranked) if r["slug"] == rating.get("slug")), None)
    return {
        "afp": rating.get("name"),
        "isa_score_relativo": rating.get("overall_score"),
        "coverage": rating.get("coverage"),
        "rank": rank,
        "n_afp_rankeadas": len(ranked),
        "periodo": rating.get("period"),
        "dimensiones": [
            {
                "dimension": d["label"], "score": d["score"], "peso": d["weight"],
                "valor_real": d["raw"], "procedencia": d["provenance"],
                "presente": d["present"],
            }
            for d in dims
        ],
        "direction": "mayor score = mejor POSICIÓN RELATIVA entre las AFP (no veredicto absoluto)",
        "source": "SIPEN — dato público real",
        "note": "Score de posición RELATIVA y PARCIAL: solvencia = brecha declarada (estados "
                "financieros pendientes), bandas absolutas DIFERIDAS. Rentabilidad nominal.",
    }


def pension_ai_context(pulse: Dict[str, Any]) -> Dict[str, Any]:
    """Compact context for the national pension-system assessment.

    *pulse* is the ``build_system_pulse`` payload. Surfaces the system rentabilidad
    and the per-AFP dispersion (top 7) so the narrative reads sustainability and
    competitive spread, not just restates a single figure.
    """
    headline = pulse.get("headline") or {}
    afp = pulse.get("afp_rentabilidad") or {}
    ranking = afp.get("ranking") or []
    return {
        "period": pulse.get("period"),
        "rentabilidad_cci_nominal": headline.get("sipen.rentabilidad.cci_nominal_anual"),
        "rentabilidad_sdp_nominal": headline.get("sipen.rentabilidad.sdp_nominal_anual"),
        "comisiones_sistema_rd_mm": headline.get("sipen.comisiones.total_anual"),
        "afp_rentabilidad": {
            "periodo": afp.get("period"),
            "ranking": [
                {"afp": r.get("name"), "rentabilidad": r.get("value")} for r in ranking
            ],
            "lider": (afp.get("leader") or {}).get("name") if afp.get("leader") else None,
            "rezagada": (afp.get("laggard") or {}).get("name") if afp.get("laggard") else None,
            "brecha_pp": afp.get("spread"),
            "promedio_simple": afp.get("average"),
        },
        "n_afp": pulse.get("entity_count"),
        "direction": "mayor cobertura/fondo y rentabilidad sostenible = sistema más sólido",
        "source": "SIPEN — sistema dominicano de pensiones (dato real)",
        "unit_rentabilidad": "% anual nominal",
        "note": "Rentabilidad NOMINAL (no descontar inflación si no está en el contexto); "
                "léela vs su promedio histórico y ajustada por riesgo, no como ranking mensual.",
    }
