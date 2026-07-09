"""DGA trade-by-partner sync — persist quarterly trade by partner country.

Reuses :class:`~modules.trade_intel.models.models.TradeFlow` (it already carries
``partner``/``period``/``direction``/``value``/``source``) with a sentinel
``product`` (:data:`PARTNER_PRODUCT`) so partner rows never mix with the by-HS-
chapter rows that :mod:`modules.trade_intel.dga_sync` writes into the same table —
no new table/migration needed. Idempotent: upsert keyed on
``(period, partner, direction)``.

Fresh quarterly geographic detail (top partners per flow) that
:data:`~modules.trade_intel.api.router` serves at ``/partners`` at the SAME quarterly
frequency as the resilience score, replacing the annual Comtrade fixture fallback.
"""
import logging
from typing import Callable, Dict, List, Optional

from sqlalchemy.orm import Session

from modules.trade_intel.models.models import TradeDirection, TradeFlow
from shared.data.dga_partners_client import (
    DGAPartnersClient,
    DGAPartnersError,
    SOURCE,
    parse_dimension,
)

logger = logging.getLogger("sdq.trade_intel.partners_sync")

# Sentinel that distinguishes partner rows from HS-chapter rows in ``ti_flows``.
PARTNER_PRODUCT = "(comercio por país)"


def is_partner_flow(flow: TradeFlow) -> bool:
    """True if a persisted flow is a partner-country row (vs an HS-chapter row)."""
    return flow.product == PARTNER_PRODUCT


def _upsert(
    db: Session, *, period: str, partner: str, direction: TradeDirection,
    value: Optional[float], unit: Optional[str], source: Optional[str],
    license_: Optional[str],
) -> bool:
    """Insert or update one partner flow. Returns True if a new row was created."""
    row = (
        db.query(TradeFlow)
        .filter_by(period=period, partner=partner, direction=direction,
                   product=PARTNER_PRODUCT)
        .first()
    )
    created = row is None
    if row is None:
        row = TradeFlow(period=period, partner=partner, direction=direction,
                        product=PARTNER_PRODUCT)
        db.add(row)
    row.value = value
    row.unit = unit
    row.source = source
    row.license = license_
    return created


def dga_partners_sync(
    db: Session,
    client: Optional[DGAPartnersClient] = None,
    set_phase: Optional[Callable[[str], None]] = None,
) -> Dict:
    """Ingest DGA trade-by-partner (quarterly, both directions) into ``TradeFlow``.

    *client* defaults to the live connector; tests pass a fixture-backed stub.
    Idempotent per ``(period, partner, direction)``. Fails closed: a connector
    error reports (never fabricates), leaving persisted data untouched.
    """
    set_phase = set_phase or (lambda _m: None)
    client = client or DGAPartnersClient(mode="live")

    set_phase("consultando comercio por país socio (DGA · Power BI)")
    try:
        records = client.fetch()
    except DGAPartnersError as e:
        logger.warning("DGA partners sync falló: %s", e)
        return {"error": str(e), "records": 0, "periods": []}

    created = 0
    updated = 0
    periods: List[str] = []
    set_phase(f"persistiendo {len(records)} filas de comercio por país")
    for r in records:
        direction_str, partner = parse_dimension(r.dimension or "")
        if direction_str not in ("export", "import") or not partner:
            continue
        direction = TradeDirection(direction_str)
        was_created = _upsert(
            db, period=r.period, partner=partner, direction=direction,
            value=r.value, unit=r.unit, source=r.lineage.source or SOURCE,
            license_=r.lineage.license,
        )
        created += int(was_created)
        updated += int(not was_created)
        periods.append(r.period)

    db.commit()
    uniq_periods = sorted(set(periods), key=lambda p: tuple(int(x) for x in p.split("-Q")))
    return {
        "records": created + updated,
        "created": created,
        "updated": updated,
        "periods": uniq_periods,
        "latest": uniq_periods[-1] if uniq_periods else None,
    }
