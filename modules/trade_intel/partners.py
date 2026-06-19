"""Partner-country concentration (Eje 6, geographic dimension).

The resilience score covers PRODUCT concentration (HHI by HS chapter). This adds
the GEOGRAPHIC dimension: how concentrated RD's trade is by partner country — the
detail the DGA Power BI doesn't export, sourced from UN Comtrade (RD as reporter).
Pure over the committed partner fixture; HHI reuses the product scorer's helper.
"""
from typing import Dict, List, Optional

from modules.trade_intel.scoring.concentration import herfindahl
from shared.data import comtrade_client as cc

_TOP_N = 8


def _block(flows: Dict[str, float]) -> Dict:
    """Concentration metrics for one direction's {partner: value} flows."""
    total = round(sum(flows.values()), 2)
    hhi = herfindahl(list(flows.values()))
    top: List[Dict] = []
    if total > 0:
        for partner, val in sorted(flows.items(), key=lambda kv: kv[1], reverse=True)[:_TOP_N]:
            top.append({"partner": partner, "value": round(val, 2), "share": round(val / total, 4)})
    return {
        "total": total,
        "hhi": hhi,
        "diversification": round((1 - hhi) * 100, 2) if hhi is not None else None,
        "n_partners": len(flows),
        "top": top,
    }


def partner_concentration_report(dataset: Optional[Dict] = None) -> Dict:
    """Latest-year partner concentration for exports + imports (geographic resilience)."""
    data = dataset if dataset is not None else cc.load_partners()
    partners = (data or {}).get("partners", {})
    if not partners:
        return {"has_data": False}
    latest = max(partners, key=int)
    return {
        "has_data": True,
        "period": latest,
        "source": (data.get("meta", {}) or {}).get("source", "UN Comtrade"),
        "export": _block(partners[latest].get("export", {})),
        "import": _block(partners[latest].get("import", {})),
    }
