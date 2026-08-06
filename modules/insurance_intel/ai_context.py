"""AI context builders for Insurance Intel narratives.

Each builder digests a read-side payload into a flat, source-stamped context dict
for ``shared.narrative`` templates. Numbers only — the narrative engine never counts,
it interprets (numeric_guard). Mirrors ``pension_intel.ai_context``.
"""
from typing import Any, Dict, List, Optional


def _dims(rating: Dict[str, Any]) -> List[Dict[str, Any]]:
    return [
        {"dimension": d["label"], "score": d.get("score"), "peso": d["weight"],
         "valor_real": d.get("raw"), "presente": d.get("present")}
        for d in rating.get("dimensions") or []
    ]


def _comparaciones(rating, peers) -> list:
    """Comparaciones dimensión↔panel con la DIRECCIÓN ya resuelta.

    Misma cura que en banca: el modelo no debe derivar "por encima / por debajo" —
    erra la relación aunque las cifras sean correctas. Se computa acá contra la MEDIANA
    del panel en cada dimensión y se sirve para que la COPIE. También es lo que activa
    el detector de ``numeric_guard``, que fuera de banca estaba ciego por depender del
    mapeo de indicadores bancarios.
    """
    import statistics as st

    from shared.narrative.derived import comparaciones_vs_referencia

    valores: Dict[str, Optional[float]] = {}
    referencias: Dict[str, Dict[str, Optional[float]]] = {}
    for d in rating.get("dimensions") or []:
        label, mio = d.get("label"), d.get("score")
        if not label or mio is None:
            continue
        otros = []
        for p in peers or []:
            for pd in p.get("dimensions") or []:
                if pd.get("label") == label and pd.get("score") is not None:
                    otros.append(float(pd["score"]))
        if len(otros) < 3:      # panel muy chico: la mediana no representa
            continue
        valores[str(label)] = float(mio)
        referencias[str(label)] = {"mediana del panel": round(st.median(otros), 2)}
    return comparaciones_vs_referencia(valores, referencias)


def _posiciones(rating: Dict[str, Any], peers: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Posición de la aseguradora en CADA dimensión, para vetar el superlativo transversal.

    El patrón nació y se curó en pensiones, pero su input (``posiciones_dimension``) sólo se
    inyectaba allí: el veto de ``numeric_guard`` se saltaba entero en seguros, así que un
    rank ISF global podía narrarse como "la más sólida del mercado" en una dimensión que
    otra lidera. Mismo helper transversal que usa banca.
    """
    from shared.narrative.derived import posiciones_por_dimension

    panel = [
        {"id": p.get("slug"), "name": p.get("name") or p.get("slug"),
         "dimensiones": {d.get("label"): d.get("score")
                         for d in (p.get("dimensions") or []) if d.get("label")}}
        for p in peers or []
    ]
    return posiciones_por_dimension(rating.get("slug"), panel)


_ANTI_SUPERLATIVO = (
    " POSICIÓN POR DIMENSIÓN: 'posiciones_dimension' trae {rank, n, es_lider, lider} por "
    "dimensión. NO afirmes que esta aseguradora es 'la mayor / la más alta / la líder del "
    "mercado' en una dimensión salvo que 'es_lider' sea true en ESA dimensión; si no lidera, "
    "da su posición real y nombra a quién lidera. El rank ISF GLOBAL no implica liderar cada "
    "dimensión. Y un percentil o un primer lugar describen la MUESTRA ACTUAL: nunca los "
    "narres como 'sin precedente' o 'nunca visto' — eso afirma sobre la historia, que no se "
    "midió."
    " DIRECCIÓN: si el contexto trae 'comparaciones', la dirección ya está resuelta "
    "ahí ('direccion': por encima / por debajo / en línea): COPIALA, no la deduzcas."
)


def insurance_entity_context(rating: Dict[str, Any], peers: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Context for a named insurer's ISF assessment (template ``insurance_entity``)."""
    ranked = [p for p in peers if p.get("overall_score") is not None]
    rank = next((i + 1 for i, p in enumerate(ranked) if p["slug"] == rating["slug"]), None)
    return {
        "aseguradora": rating.get("name") or rating.get("slug"),
        "isf_score": rating.get("overall_score"),
        "banda": rating.get("band"),
        "coverage": rating.get("coverage"),
        "rank": rank,
        "n_aseguradoras_rankeadas": len(ranked),
        "periodo": rating.get("period"),
        "dimensiones": _dims(rating),
        "posiciones_dimension": _posiciones(rating, peers),
        "comparaciones": _comparaciones(rating, peers),
        "direction": "mayor solvencia/liquidez/resultado y menor siniestralidad = más sólida",
        "source": "SIS — estados financieros auditados por compañía (dato real)",
        "note": ("El ISF integra cinco dimensiones sobre los estados financieros auditados que "
                 "publica la SIS: solvencia (patrimonio/activos), siniestralidad (loss ratio), "
                 "liquidez, escala y resultado técnico. Es una medida de solidez por bandas, no "
                 "un rating de crédito ni una clasificación de Solvencia II." + _ANTI_SUPERLATIVO),
    }


def insurance_peer_context(name: str, rating: Dict[str, Any],
                           peers: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Context for peer positioning against the market (template ``insurance_peer_positioning``)."""
    ranked = sorted((p for p in peers if p.get("overall_score") is not None),
                    key=lambda p: p["overall_score"], reverse=True)
    def _cell(p: Dict[str, Any]) -> Dict[str, Any]:
        by = {d["key"]: d.get("score") for d in p.get("dimensions") or []}
        return {"aseguradora": p.get("name") or p.get("slug"), "isf": p.get("overall_score"),
                "solvencia": by.get("solvencia"), "siniestralidad": by.get("siniestralidad"),
                "liquidez": by.get("liquidez"), "escala": by.get("escala"),
                "resultado_tecnico": by.get("resultado_tecnico")}
    rank = next((i + 1 for i, p in enumerate(ranked) if p["slug"] == rating["slug"]), None)
    avg = round(sum(p["overall_score"] for p in ranked) / len(ranked), 1) if ranked else None
    return {
        "aseguradora": name, "isf": rating.get("overall_score"), "banda": rating.get("band"),
        "rank": rank, "n_aseguradoras_rankeadas": len(ranked),
        "tabla_pares": [_cell(p) for p in ranked[:12]],
        "lider_isf": ranked[0].get("name") if ranked else None,
        "promedio_isf": avg,
        "posiciones_dimension": _posiciones(rating, peers),
        "comparaciones": _comparaciones(rating, peers),
        "source": "SIS — estados financieros auditados por compañía (dato real)",
        "note": ("Posición relativa por bandas de solidez (0-100). No es un rating de crédito."
                 + _ANTI_SUPERLATIVO),
    }


def market_pulse_context(pulse: Dict[str, Any]) -> Dict[str, Any]:
    """Context for the national insurance-market Pulse (template ``insurance_pulse``)."""
    mix: List[Dict[str, Any]] = pulse.get("mix") or []
    hc = pulse.get("health_coverage") or {}
    return {
        "periodo": pulse.get("period"),
        "cobertura_salud_sfs": {
            "afiliados_total": hc.get("afiliados_total"),
            "afiliados_contributivo": hc.get("afiliados_contributivo"),
            "afiliados_subsidiado": hc.get("afiliados_subsidiado"),
            "crecimiento_5a_pct": hc.get("crecimiento_5a_pct"),
            "periodo": hc.get("period"),
            "fuente": "SISALRIL/CNSS — Seguro Familiar de Salud",
        } if hc else None,
        "anio": pulse.get("latest_year"),
        "primas_totales_rd": pulse.get("total_premiums_rd"),
        "crecimiento_pct": pulse.get("growth_pct"),
        "crecimiento_ventana": pulse.get("growth_years"),
        "aseguradoras_activas": pulse.get("active_insurers"),
        "n_ramos": pulse.get("n_ramos"),
        "concentracion_top4_pct": pulse.get("top4_concentration_pct"),
        "mezcla_por_ramo": [
            {"ramo": d["label"], "monto_rd": d["amount"], "pct": d.get("pct")}
            for d in mix[:6]
        ],
        "unit_primas": "RD$ (primas netas cobradas)",
        "direction": "mayor tamaño, crecimiento sostenido y mezcla diversificada = mercado más profundo",
        "source": "SIS — Superintendencia de Seguros (dato real, datos.gob.do)",
        "note": (
            "Pulso del mercado asegurador (agregado, sin nombres de aseguradora). "
            "Primas netas cobradas; el crecimiento se lee como tasa compuesta entre años "
            "independientes. " + (pulse.get("data_caveat") or "")
        ).strip(),
    }
