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


def pension_cartera_context(cartera: Dict[str, Any]) -> Dict[str, Any]:
    """Compact context for the portfolio-composition narrative (template ``pension_cartera``).

    *cartera* is the ``/cartera`` payload. Surfaces the top-level composition (sub-sector
    rollups + the sovereign leaves Hacienda/BCRD), the sovereign concentration, and the
    largest individual bank exposures — never the full 77-issuer list, so prompts stay
    cheap. All figures are copied from the reconciled real table.
    """
    holdings = cartera.get("holdings") or []
    summary = cartera.get("summary") or {}
    # Top-level rows partition the total: sub-sector headers + standalone leaves (Hacienda,
    # BCRD, which have no parent group).
    top_level = [
        h for h in holdings
        if h.get("amount") is not None and (h.get("is_subtotal") or h.get("sub_sector") is None)
    ]
    composicion = sorted(
        ({"categoria": h["issuer"], "monto_rd": h["amount"], "pct": h["pct"]} for h in top_level),
        key=lambda x: x["monto_rd"], reverse=True,
    )
    bancos = sorted(
        ({"banco": h["issuer"], "monto_rd": h["amount"], "pct": h["pct"]}
         for h in holdings
         if not h.get("is_subtotal") and h.get("sub_sector") == "Bancos Múltiples"
         and h.get("amount") is not None),
        key=lambda x: x["monto_rd"], reverse=True,
    )[:5]
    return {
        "periodo": cartera.get("period"),
        "fondo": cartera.get("fund"),
        "total_cartera_rd": cartera.get("total"),
        "deuda_publica_pct": summary.get("public_debt_pct"),
        "bcrd_pct": summary.get("bcrd_pct"),
        "n_emisores": summary.get("issuer_count"),
        "composicion_por_categoria": composicion,
        "top_bancos": bancos,
        "source": "SIPEN — Cuadro 6.1 del boletín trimestral (dato real)",
        "unit": "RD$ corrientes y % del fondo",
        "note": "FOTO trimestral de la cartera; montos en RD$ corrientes. No es serie ni "
                "juicio de riesgo crediticio de un emisor; lee concentración y rol institucional.",
    }


def pension_indicator_context(
    code: str, label: str, unit: str, points: List[tuple],
) -> Dict[str, Any]:
    """Compact context for one SYSTEM indicator's drill-down (template
    ``pension_system_indicator``). *points* = ``[(period, value)]`` ascending."""
    latest = points[-1] if points else (None, None)
    first = points[0] if points else (None, None)
    return {
        "indicador": label, "code": code, "unit": unit,
        "valor_actual": latest[1], "periodo": latest[0],
        "desde": first[0], "n_obs": len(points),
        "serie_reciente": [{"periodo": p, "valor": v} for p, v in points[-12:]],
        "source": "SIPEN — sistema dominicano de pensiones (dato real)",
        "note": "Lee la TENDENCIA de la serie, no un solo mes. Si es rentabilidad, es NOMINAL.",
    }


def pension_dimension_context(
    afp_name: str, dim: Dict[str, Any], peers: List[Dict[str, Any]],
    trend: List[tuple],
) -> Dict[str, Any]:
    """Compact context for one AFP DIMENSION drill-down (template ``pension_afp_dimension``).

    *dim* is this AFP's dimension breakdown (label/raw/score/weight/direction/provenance/present);
    *peers* = ``[{afp, raw, score}]`` across the panel; *trend* = ``[(period, raw)]`` ascending."""
    ranked = sorted(
        [p for p in peers if p.get("score") is not None],
        key=lambda p: p["score"], reverse=True,
    )
    rank = next((i + 1 for i, p in enumerate(ranked) if p["afp"] == afp_name), None)
    return {
        "afp": afp_name,
        "dimension": dim.get("label"),
        "peso": dim.get("weight"),
        "direccion": "mayor es mejor" if dim.get("direction") == "higher" else "menor es mejor",
        "procedencia": dim.get("provenance"),
        "presente": dim.get("present"),
        "valor_real": dim.get("raw"),
        "score_relativo": dim.get("score"),
        "rank": rank,
        "n_afp_con_dato": len(ranked),
        "pares": [{"afp": p["afp"], "valor_real": p["raw"], "score": p["score"]} for p in peers],
        "serie_reciente": [{"periodo": p, "valor": v} for p, v in trend[-12:]],
        "source": "SIPEN — dato real",
        "note": "Score = POSICIÓN RELATIVA (peer min-max), no veredicto absoluto. Si la dimensión "
                "es solvencia y es brecha declarada, dilo y no inventes cifra.",
    }


def pension_cartera_item_context(
    holding: Dict[str, Any], total: float, period: str,
) -> Dict[str, Any]:
    """Compact context for one cartera POSITION drill-down (template ``pension_cartera_item``)."""
    macro = holding.get("macro_class")
    naturaleza = ("deuda pública (exposición soberana del ahorro)" if macro == "deuda_publica"
                  else "Banco Central" if macro == "bcrd"
                  else "sub-sector / emisor de la cartera")
    return {
        "posicion": holding.get("issuer"),
        "sub_sector": holding.get("sub_sector"),
        "es_subtotal": holding.get("is_subtotal"),
        "naturaleza": naturaleza,
        "monto_rd": holding.get("amount"),
        "pct_cartera": holding.get("pct"),
        "cartera_total_rd": total,
        "periodo": period,
        "source": "SIPEN — Cuadro 6.1 del boletín trimestral (dato real)",
        "unit": "RD$ corrientes y % del fondo",
        "note": "FOTO trimestral; no juicio de riesgo crediticio del emisor. Lee concentración y rol.",
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
