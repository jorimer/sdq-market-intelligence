"""Entity-level drill-down: overall rating + sub-component drivers + peers + AI.

Powers the entity drawer (Rankings/Dashboard). Reuses the stored RatingResult
(overall score, sub-component scores, indicator_details) — no re-ingest — and the
indicator metadata. The AI "fundamento del rating" is generated in the API layer.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from sqlalchemy.orm import Session

from modules.banking_score.models.models import Bank, ModelType, RatingResult
from modules.banking_score.scoring.indicator_detail import INDICATOR_META, _band, _peer_stats
from modules.banking_score.scoring.weights import (
    CALIDAD_INDICATORS,
    DIVERSIFICACION_INDICATORS,
    EFICIENCIA_INDICATORS,
    LIQUIDEZ_INDICATORS,
    SOLIDEZ_INDICATORS,
    SUB_COMPONENT_WEIGHTS,
)

_SUB_LABELS = {
    "solidez": "Solidez financiera",
    "calidad": "Calidad de activos",
    "eficiencia": "Eficiencia y rentabilidad",
    "liquidez": "Liquidez",
    "diversificacion": "Diversificación",
}

# Sub-component → its scoring indicators (drop the composite aggregate).
_SUB_GROUPS = {
    "solidez": SOLIDEZ_INDICATORS,
    "calidad": [k for k in CALIDAD_INDICATORS if k in INDICATOR_META],
    "eficiencia": EFICIENCIA_INDICATORS,
    "liquidez": LIQUIDEZ_INDICATORS,
    "diversificacion": DIVERSIFICACION_INDICATORS,
}


def _sub_scores(rr: RatingResult) -> Dict[str, Optional[float]]:
    def _f(v):
        return float(v) if v is not None else None
    return {
        "solidez": _f(rr.solidez_score),
        "calidad": _f(rr.calidad_score),
        "eficiencia": _f(rr.eficiencia_score),
        "liquidez": _f(rr.liquidez_score),
        "diversificacion": _f(rr.diversificacion_score),
    }


def _driver_drag(details: Dict[str, Any], keys: List[str]) -> Dict[str, Optional[Dict]]:
    """Highest-scoring (driver) and lowest-scoring (drag) available indicator in a group."""
    avail = [
        {"key": k, "label": INDICATOR_META[k]["label"], "score": float(d["score"])}
        for k in keys
        if (d := details.get(k)) and d.get("available") is not False and d.get("score") is not None
        and k in INDICATOR_META
    ]
    if not avail:
        return {"driver": None, "drag": None}
    avail.sort(key=lambda x: x["score"])
    return {"drag": avail[0], "driver": avail[-1]}


def build_entity_insight(db: Session, bank: Bank) -> Optional[Dict[str, Any]]:
    """Assemble the deterministic entity drill-down (no AI). None if no ratings."""
    ratings = (
        db.query(RatingResult)
        .filter(RatingResult.bank_id == bank.id,
                RatingResult.model_type == ModelType.deterministic)
        .order_by(RatingResult.period_end.asc())
        .all()
    )
    if not ratings:
        return None

    latest = ratings[-1]
    overall = float(latest.overall_score)
    subs = _sub_scores(latest)
    details = latest.indicator_details or {}
    period_end = latest.period_end

    sub_components = []
    for key, label in _SUB_LABELS.items():
        score = subs.get(key)
        sub_components.append({
            "key": key,
            "label": label,
            "score": score,
            "weight": SUB_COMPONENT_WEIGHTS.get(key),
            "band": _band(score) if score is not None else None,
            **_driver_drag(details, _SUB_GROUPS[key]),
        })

    # Overall-score trend
    trend = [{"period_end": str(r.period_end), "score": float(r.overall_score),
              "tier": r.rating_tier} for r in ratings]

    # Peers: overall-score distribution at the latest period (sector + same type)
    peer_rows = (
        db.query(RatingResult, Bank.bank_type)
        .join(Bank, Bank.id == RatingResult.bank_id)
        .filter(RatingResult.period_end == period_end,
                RatingResult.model_type == ModelType.deterministic)
        .all()
    )
    sector_scores = [float(r.overall_score) for r, _ in peer_rows]
    type_scores = [float(r.overall_score) for r, bt in peer_rows
                   if bank.bank_type is not None and bt == bank.bank_type]

    return {
        "bank_id": bank.id,
        "bank_name": bank.name,
        "entity_type": bank.bank_type.value if bank.bank_type else None,
        "latest": {
            "period_end": str(period_end),
            "overall_score": round(overall, 2),
            "rating_tier": latest.rating_tier,
            "band": _band(overall),
        },
        "sub_components": sub_components,
        "trend": trend,
        "peers": {
            "period_end": str(period_end),
            "sector": _peer_stats(sector_scores, overall),
            "entity_type": _peer_stats(type_scores, overall),
            "entity_type_label": bank.bank_type.value if bank.bank_type else None,
        },
    }


def ai_context_entity(detail: Dict[str, Any]) -> Dict[str, Any]:
    """Compact context for the entity AI narrative."""
    window = detail["trend"][-12:]
    return {
        "entidad": detail["bank_name"],
        "tipo_entidad": detail["entity_type"],
        "periodo": detail["latest"]["period_end"],
        "rating": detail["latest"]["rating_tier"],
        "score_global": detail["latest"]["overall_score"],
        "sub_componentes": [
            {"componente": s["label"], "score": s["score"], "peso": s["weight"],
             "impulsor": (s["driver"] or {}).get("label"),
             "lastre": (s["drag"] or {}).get("label")}
            for s in detail["sub_components"]
        ],
        "pares": detail.get("peers"),
        "tendencia_score": [{"periodo": t["period_end"], "score": t["score"]}
                            for t in window],
        # Cifras derivadas YA CALCULADAS — el analista DEBE copiarlas, no recomputarlas
        # (el LLM erraba deltas, aportes y rangos). Ver _derived_figures.
        "cifras_derivadas": _derived_figures(detail, window),
    }


def _derived_figures(detail: Dict[str, Any], window: list) -> Dict[str, Any]:
    """Pre-compute the derived figures the model tends to miscompute: weighted
    contribution per sub-component, deltas vs peer medians/p75, the 12-quarter score
    range (with periods), and the Q1/March closes (with periods)."""
    out: Dict[str, Any] = {}
    score = detail["latest"].get("overall_score")

    out["aporte_por_componente"] = [
        {"componente": s["label"],
         "aporte_pts": round((s["score"] or 0) * (s["weight"] or 0), 2)}
        for s in detail["sub_components"]
    ]

    peers = detail.get("peers") or {}
    if score is not None:
        deltas: Dict[str, Any] = {}
        et = peers.get("entity_type") or {}
        sec = peers.get("sector") or {}
        if et.get("median_score") is not None:
            deltas["vs_mediana_tipo"] = round(score - et["median_score"], 2)
        if et.get("p75_score") is not None:
            deltas["vs_p75_tipo"] = round(score - et["p75_score"], 2)
        if sec.get("median_score") is not None:
            deltas["vs_mediana_sector"] = round(score - sec["median_score"], 2)
        if deltas:
            out["delta_score"] = deltas

    scores = [(t["period_end"], t["score"]) for t in window if t.get("score") is not None]
    if scores:
        lo = min(scores, key=lambda x: x[1])
        hi = max(scores, key=lambda x: x[1])
        out["rango_score_12t"] = {
            "min": {"periodo": lo[0], "score": lo[1]},
            "max": {"periodo": hi[0], "score": hi[1]},
            "n_periodos": len(scores),
        }
    cortes_q1 = [{"periodo": t["period_end"], "score": t["score"]}
                 for t in window if str(t.get("period_end") or "")[5:7] == "03"]
    if cortes_q1:
        out["cortes_q1_marzo"] = cortes_q1
    return out
