"""Trade resilience scoring (Eje 6).

Doctrine (§8): *diversification > volume*; *dynamic upgrading > static comparative
advantage*; *measure dependence, not just openness*.

Pure functions over a list of flows::

    {"product": "ferronickel", "direction": "export", "value": 1200.0,
     "partner": "US"}

Core metrics:
  * **HHI** of export concentration by product (Herfindahl-Hirschman, 0-1).
  * **export_diversification** = (1 - HHI) * 100  (higher = more diversified = better).
  * **import_dependency** = imports / (exports + imports).
  * **resilience_score** (0-100): explainable blend of the two.
"""
from collections import defaultdict
from typing import Dict, List, Optional

Flow = Dict[str, object]

# Resilience blend weights (diversification vs. import independence).
W_DIVERSIFICATION = 0.6
W_INDEPENDENCE = 0.4


def _totals_by_product(flows: List[Flow], direction: str) -> Dict[str, float]:
    out: Dict[str, float] = defaultdict(float)
    for f in flows:
        if f.get("direction") == direction and f.get("value") is not None:
            out[str(f.get("product", "—"))] += float(f["value"])
    return dict(out)


def herfindahl(values: List[float]) -> Optional[float]:
    """HHI over a set of values (sum of squared shares), 0-1.  None if no volume."""
    total = sum(v for v in values if v is not None)
    if total <= 0:
        return None
    return round(sum((v / total) ** 2 for v in values if v is not None), 4)


def compute_trade_scores(flows: List[Flow]) -> Dict:
    """Compute concentration, dependency and a resilience score from *flows*."""
    exports = _totals_by_product(flows, "export")
    imports = _totals_by_product(flows, "import")

    total_exports = round(sum(exports.values()), 2)
    total_imports = round(sum(imports.values()), 2)

    hhi = herfindahl(list(exports.values()))
    export_diversification = round((1 - hhi) * 100, 2) if hhi is not None else None

    denom = total_exports + total_imports
    import_dependency = round(total_imports / denom, 4) if denom > 0 else None

    # Top export products by share (explainability).
    top_products = []
    if total_exports > 0:
        for product, val in sorted(exports.items(), key=lambda kv: kv[1], reverse=True)[:5]:
            top_products.append({
                "product": product,
                "value": round(val, 2),
                "share": round(val / total_exports, 4),
            })

    resilience_score = None
    if export_diversification is not None and import_dependency is not None:
        resilience_score = round(
            W_DIVERSIFICATION * export_diversification
            + W_INDEPENDENCE * (1 - import_dependency) * 100,
            2,
        )

    return {
        "hhi_exports": hhi,
        "export_diversification": export_diversification,
        "import_dependency": import_dependency,
        "resilience_score": resilience_score,
        "total_exports": total_exports,
        "total_imports": total_imports,
        "top_export_products": top_products,
        "n_products_export": len(exports),
        "n_products_import": len(imports),
    }
