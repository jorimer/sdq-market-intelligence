"""Trade Intel — persistence, scoring and events.

Flows are supplied explicitly (DGA/customs live ingestion is deferred until its
license is confirmed — `shared/data/dga_client` has ``license_ok=False``).  The
service persists the flows, computes the resilience score and publishes
``trade.updated``.
"""
import logging
from typing import Any, Dict, List, Optional

from sqlalchemy.orm import Session

from modules.trade_intel.events import publish_trade_updated
from modules.trade_intel.models.models import TradeDirection, TradeFlow, TradeScore
from modules.trade_intel.scoring.concentration import compute_trade_scores

logger = logging.getLogger("sdq.trade_intel.service")

MODEL_VERSION = "1.0"


def _persist_flows(db: Session, period: str, flows: List[Dict[str, Any]]) -> None:
    """Replace the CHAPTER flows for *period* — nunca las filas de otro tipo.

    ``ti_flows`` guarda dos clases de fila distinguidas por un centinela en ``product``: los
    capítulos HS (esta función) y el comercio por PAÍS que escribe ``partners_sync``. El
    borrado era por período a secas, así que un sync de capítulos arrasaba las filas de socio
    del mismo trimestre. Hoy no se nota sólo porque el sync de socios corrió después; con la
    cadencia anclada, el de capítulos pasa a correr antes y la pérdida se materializaba.

    Verificado en prod (2026-08-13): 2026-Q2 tenía 60 filas de socio y 0 de capítulo —el
    trimestre a medio ingerir—, justo las que el próximo sync de capítulos habría borrado.
    """
    from modules.trade_intel.partners_sync import PARTNER_PRODUCT

    (db.query(TradeFlow)
     .filter(TradeFlow.period == period, TradeFlow.product != PARTNER_PRODUCT)
     .delete(synchronize_session=False))
    for f in flows:
        db.add(TradeFlow(
            product=str(f["product"]),
            direction=TradeDirection(f["direction"]),
            value=None if f.get("value") is None else float(f["value"]),
            period=period,
            partner=f.get("partner"),
            unit=f.get("unit"),
            source=f.get("source"),
            license=f.get("license"),
        ))


def compute_and_persist(
    db: Session, period: str, flows: List[Dict[str, Any]]
) -> Dict[str, Any]:
    """Persist *flows*, compute the trade score for *period*, publish ``trade.updated``.

    Idempotent per period: re-running replaces the flows and the score in place.
    """
    if not flows:
        raise ValueError("Se requiere al menos un flujo comercial.")

    scores = compute_trade_scores(flows)
    _persist_flows(db, period, flows)

    score = db.query(TradeScore).filter_by(period=period).first()
    if score is None:
        score = TradeScore(period=period)
        db.add(score)
    score.hhi_exports = scores["hhi_exports"]
    score.export_diversification = scores["export_diversification"]
    score.import_dependency = scores["import_dependency"]
    score.resilience_score = scores["resilience_score"]
    score.breakdown = scores
    score.model_version = MODEL_VERSION

    db.commit()
    db.refresh(score)

    payload = {
        "period": period,
        "resilience_score": scores["resilience_score"],
        "export_diversification": scores["export_diversification"],
        "import_dependency": scores["import_dependency"],
    }
    publish_trade_updated(payload)
    logger.info(
        "Trade score %s: resiliencia=%s diversificación=%s",
        period, scores["resilience_score"], scores["export_diversification"],
    )
    return {"period": period, "score_id": score.id, **scores, "model_version": MODEL_VERSION}


def get_latest_score(db: Session, period: Optional[str] = None) -> Optional[TradeScore]:
    q = db.query(TradeScore)
    if period:
        return q.filter_by(period=period).first()
    return q.order_by(TradeScore.period.desc()).first()


def get_flows(db: Session, period: Optional[str] = None) -> List[TradeFlow]:
    q = db.query(TradeFlow)
    if period:
        q = q.filter_by(period=period)
    return q.order_by(TradeFlow.value.desc().nullslast()).all()
