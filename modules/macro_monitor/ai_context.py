"""Compact AI contexts for macro_monitor narratives.

The narrative engine receives a SMALL, pre-digested context (recent values,
momentum, signals) — never the whole series/snapshot object — so prompts stay
cheap and focused (plan §5.2). Module-local (macro_monitor does not import from
other feature modules).
"""
from typing import Any, Dict, List, Optional


def series_ai_context(detail: Dict[str, Any], meta: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Compact context for a single series' trend analysis.

    *detail* is :func:`get_series` output; *meta* is the matching indicator row
    (label/unit/trend/acceleration) from :func:`get_indicators`, when available.
    """
    obs: List[Dict[str, Any]] = detail.get("observations") or []
    mom = detail.get("momentum") or {}
    meta = meta or {}

    def _pick(key: str):
        if meta.get(key) is not None:
            return meta.get(key)
        return mom.get(key) if isinstance(mom, dict) else None

    return {
        "series_code": detail.get("series_code"),
        "label": meta.get("label"),
        "unit": meta.get("unit"),
        "trend": meta.get("trend"),
        "latest_period": meta.get("latest_period"),
        "latest_value": _pick("latest_value"),
        "change": _pick("change"),
        "pct_change": meta.get("pct_change"),
        "acceleration": meta.get("acceleration"),
        "n_obs": len(obs),
        "recent_observations": obs[-6:],
    }


def snapshot_ai_context(snapshot: Dict[str, Any],
                        indicators: Optional[List[Dict[str, Any]]] = None) -> Dict[str, Any]:
    """Compact context for the macro snapshot (coyuntura) executive summary.

    Includes the early-warning signals and the few biggest movers by absolute
    acceleration — not every series. Note: *indicators* carries each series' LATEST
    momentum (from get_indicators), so when a historical ``period`` snapshot is
    requested the movers reflect the latest read, not that period's. The UI only
    requests the latest snapshot, so signals and movers stay consistent there.
    """
    movers = [
        {
            "label": i.get("label"),
            "series_code": i.get("series_code"),
            "latest_value": i.get("latest_value"),
            "unit": i.get("unit"),
            "trend": i.get("trend"),
            "acceleration": i.get("acceleration"),
            "pct_change": i.get("pct_change"),
        }
        for i in (indicators or [])
        if i.get("acceleration") is not None
    ]
    movers.sort(key=lambda m: abs(m["acceleration"]), reverse=True)

    return {
        "period": snapshot.get("period"),
        "series_count": snapshot.get("series_count"),
        "signal_count": snapshot.get("signal_count"),
        "signals": snapshot.get("signals") or [],
        "top_movers": movers[:6],
    }


def fiscal_ai_context(pulse: Dict[str, Any]) -> Dict[str, Any]:
    """Compact context for the fiscal-pulse executive summary (SCQA).

    Only what matters at the fiscal level: the latest ingresos/gastos/déficit, the
    recent deficit trajectory (last 12 months) and the top recaudación lines — not
    every monthly point. ``has_data`` False yields a minimal context the template
    renders as "sin datos"."""
    if not pulse.get("has_data"):
        return {"title": "Pulso fiscal", "has_data": False}
    lat = pulse.get("eo_latest") or {}
    deficit_recent = [
        {"period": d["period"], "value": d["value"]}
        for d in (pulse.get("eo", {}).get("balance_global") or [])[-12:]
    ]
    rec = pulse.get("recaudacion") or {}
    return {
        "title": "Pulso fiscal — Gobierno Central",
        "has_data": True,
        "period": pulse.get("latest_period"),
        "unit": pulse.get("eo_unit"),
        "ingresos": lat.get("ingresos"),
        "gastos": lat.get("gastos"),
        "balance_global": lat.get("balance_global"),
        "deficit_ultimos_12m": deficit_recent,
        "recaudacion_unit": pulse.get("recaudacion_unit"),
        "recaudacion_top": [
            {"label": g.get("label"), "value": g.get("value")}
            for g in (rec.get("groups") or [])[:5]
        ],
    }
