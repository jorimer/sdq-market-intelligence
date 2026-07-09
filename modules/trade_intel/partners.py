"""Partner-country concentration (Eje 6, geographic dimension).

The resilience score covers PRODUCT concentration (HHI by HS chapter). This adds
the GEOGRAPHIC dimension: how concentrated RD's trade is by partner country.

Two sources, preferred in order:
  1. **DGA (Power BI)** — fresh, QUARTERLY partner flows persisted in ``TradeFlow``
     (via ``dga-partners-sync``). Same frequency as the resilience score.
  2. **UN Comtrade** — the committed annual fixture, used only as a fallback so the
     endpoint always answers; labelled ``frequency="anual"`` so the caller never
     confuses it with the fresh quarterly cut.

HHI reuses the product scorer's helper.
"""
from typing import Dict, List, Optional

from sqlalchemy.orm import Session

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


def _period_sort_key(period: str) -> tuple:
    """Sort ``"2025-Q3"`` (quarterly) or ``"2024"`` (annual) chronologically."""
    if "-Q" in period:
        year, quarter = period.split("-Q")
        return (int(year), int(quarter))
    return (int(period), 0)


def dga_partner_report(db: Session) -> Optional[Dict]:
    """Partner concentration from the FRESH DGA quarterly flows persisted in ``TradeFlow``.

    Returns ``None`` when no DGA partner rows are persisted (caller falls back to the
    Comtrade annual fixture). Metadata is explicit: ``source``/``period`` and
    ``frequency="trimestral"`` so callers never mistake it for the annual cut.
    """
    from modules.trade_intel.models.models import TradeDirection, TradeFlow
    from modules.trade_intel.partners_sync import PARTNER_PRODUCT

    rows = (
        db.query(TradeFlow)
        .filter(TradeFlow.product == PARTNER_PRODUCT)
        .all()
    )
    if not rows:
        return None
    latest = max((r.period for r in rows), key=_period_sort_key)
    exports: Dict[str, float] = {}
    imports: Dict[str, float] = {}
    source = "DGA (Power BI)"
    for r in rows:
        if r.period != latest or r.value is None or not r.partner:
            continue
        source = r.source or source
        bucket = exports if r.direction == TradeDirection.export else imports
        bucket[r.partner] = bucket.get(r.partner, 0.0) + float(r.value)
    return {
        "has_data": True,
        "period": latest,
        "source": source,
        "frequency": "trimestral",
        "unit": "USD",
        "export": _block(exports),
        "import": _block(imports),
    }


def partner_concentration_report(
    dataset: Optional[Dict] = None, db: Optional[Session] = None
) -> Dict:
    """Latest partner concentration for exports + imports (geographic resilience).

    Prefers fresh DGA quarterly flows when a *db* session is given and rows exist;
    otherwise falls back to the (annual) Comtrade fixture, labelled as such so the
    caller can always tell source and frequency of every figure.
    """
    if db is not None and dataset is None:
        dga = dga_partner_report(db)
        if dga is not None:
            return dga

    data = dataset if dataset is not None else cc.load_partners()
    partners = (data or {}).get("partners", {})
    if not partners:
        return {"has_data": False}
    latest = max(partners, key=int)
    return {
        "has_data": True,
        "period": latest,
        "source": (data.get("meta", {}) or {}).get("source", "Comtrade"),
        "frequency": "anual",
        "unit": "USD",
        "export": _block(partners[latest].get("export", {})),
        "import": _block(partners[latest].get("import", {})),
    }
