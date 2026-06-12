"""Macro Monitor — ingestion, snapshot computation, persistence & events.

Pipeline:
    1. ingest_series: pull records from a shared/data source → upsert MacroSeries.
    2. build_snapshot: compute per-series momentum + early-warning signals,
       persist a MacroSnapshot and publish ``macro.updated``.

The scoring (`scoring/momentum.py`, `scoring/signals.py`) is pure; this layer
wires it to the DB, the data layer and the event bus.
"""
import logging
from collections import defaultdict
from typing import Any, Dict, List, Optional

from sqlalchemy.orm import Session

from shared.data.base_client import SourceClient
from shared.data.bcrd_client import bcrd_client, resolve_bcrd_client
from modules.macro_monitor.events import publish_macro_updated
from modules.macro_monitor.models.models import MacroSeries, MacroSnapshot
from modules.macro_monitor.scoring.momentum import compute_series_momentum
from modules.macro_monitor.scoring.signals import detect_signals

logger = logging.getLogger("sdq.macro_monitor.service")

MODEL_VERSION = "1.0"

# Series used by the early-warning signals.
DEBT_SERIES = "public_debt_gdp"
FLOW_SERIES = {"remittances", "fdi", "reserves", "exports", "capital_flows"}


def ingest_series(db: Session, client: Optional[SourceClient] = None) -> int:
    """Upsert observations from *client* into MacroSeries.  Returns rows touched.

    When *client* is omitted, resolves the BCRD source: live API if a token is
    configured+enabled (Configuración → BCRD), otherwise the local fixture.
    """
    if client is None:
        client = resolve_bcrd_client(db)
    records = client.fetch()
    touched = 0
    for r in records:
        row = (
            db.query(MacroSeries)
            .filter_by(series_code=r.series, period=r.period)
            .first()
        )
        lic = r.lineage.license if r.lineage else None
        pub = r.lineage.published_at if r.lineage else None
        src = r.lineage.source if r.lineage else None
        if row is None:
            db.add(MacroSeries(
                series_code=r.series, period=r.period, value=r.value,
                unit=r.unit, source=src, published_at=pub, license=lic,
            ))
        else:
            row.value = r.value
            row.unit = r.unit
            row.source = src
            row.published_at = pub
            row.license = lic
        touched += 1
    db.commit()
    logger.info("Ingesta macro: %d observaciones (%s)", touched, client.source)
    return touched


def _series_by_code(db: Session) -> Dict[str, List[tuple]]:
    """Group all observations into ``{series_code: [(period, value), ...]}`` sorted."""
    grouped: Dict[str, list] = defaultdict(list)
    for row in db.query(MacroSeries).all():
        grouped[row.series_code].append((row.period, row.value))
    for code in grouped:
        grouped[code].sort(key=lambda pv: pv[0])
    return grouped


def build_snapshot(db: Session, period: Optional[str] = None) -> Dict[str, Any]:
    """Compute momentum + signals across all series, persist and publish.

    *period* labels the snapshot; defaults to the latest period observed.
    """
    grouped = _series_by_code(db)
    if not grouped:
        raise ValueError("No hay series macro ingeridas; corra ingest_series primero.")

    momentum = {code: compute_series_momentum(obs) for code, obs in grouped.items()}

    # Early-warning inputs.
    debt_obs = grouped.get(DEBT_SERIES, [])
    debt_latest = next((v for _, v in reversed(debt_obs) if v is not None), None)
    flow_pct = {
        code: momentum[code]["pct_change"]
        for code in grouped if code in FLOW_SERIES
    }
    signals = detect_signals(debt_latest, flow_pct)

    if period is None:
        period = max(p for obs in grouped.values() for p, _ in obs)

    snapshot = db.query(MacroSnapshot).filter_by(period=period).first()
    if snapshot is None:
        snapshot = MacroSnapshot(period=period)
        db.add(snapshot)
    snapshot.momentum = momentum
    snapshot.signals = signals
    snapshot.series_count = len(grouped)
    snapshot.signal_count = len(signals)
    snapshot.model_version = MODEL_VERSION

    db.commit()
    db.refresh(snapshot)

    payload = {
        "period": period,
        "series_count": len(grouped),
        "signal_count": len(signals),
        "signals": signals,
    }
    publish_macro_updated(payload)
    logger.info(
        "Snapshot macro %s: %d series, %d señales", period, len(grouped), len(signals)
    )
    return {
        "period": period,
        "snapshot_id": snapshot.id,
        "series_count": len(grouped),
        "momentum": momentum,
        "signals": signals,
        "model_version": MODEL_VERSION,
    }


def get_indicators(db: Session) -> List[Dict[str, Any]]:
    """Latest momentum read per series (for the /indicators view)."""
    grouped = _series_by_code(db)
    out = []
    for code, obs in sorted(grouped.items()):
        m = compute_series_momentum(obs)
        out.append({"series_code": code, **m})
    return out


def get_series(db: Session, series_code: str) -> Dict[str, Any]:
    """Return one series' observations (period-ordered) + its momentum read."""
    grouped = _series_by_code(db)
    obs = grouped.get(series_code, [])
    momentum = compute_series_momentum(obs) if obs else None
    return {
        "series_code": series_code,
        "observations": [{"period": p, "value": v} for p, v in obs],
        "momentum": momentum,
    }


def get_snapshot(db: Session, period: Optional[str] = None) -> Optional[MacroSnapshot]:
    """Persisted snapshot for *period* (latest if omitted)."""
    q = db.query(MacroSnapshot)
    if period:
        return q.filter_by(period=period).first()
    return q.order_by(MacroSnapshot.period.desc()).first()
