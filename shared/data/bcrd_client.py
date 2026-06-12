"""Banco Central de la República Dominicana (BCRD) connector.

Feeds `macro_monitor` (Eje 2) and the macro/external dimensions of the IRMP and
sector indices. Two modes behind one interface (see :mod:`shared.data.base_client`):

* ``fixture`` — versioned local data (default; no credentials).
* ``live`` — the real BCRD MacroVariables API (token in the POST body, restricted
  by IPv4 allowlist). Each variable returns groups → metrics; we flatten them into
  :class:`Record`s with stable slug series codes. Shapes verified 2026-06.
"""
from __future__ import annotations

import logging
import unicodedata
from datetime import date
from typing import Any, Dict, List, Optional

import httpx

from shared.data.base_client import FixtureBackedClient, Record
from shared.data.bcrd_api import BCRD_BASE_URL, BcrdApiError, fetch_bcrd_variable
from shared.data.lineage import Lineage

logger = logging.getLogger("sdq.data.bcrd")

# Variables we ingest live. ``historico_tasas`` returns an internal error from the
# BCRD and ``historico_ipc`` needs date-range params, so both are excluded here.
LIVE_VARIABLES = ["inflacion", "monetarias", "sector_real", "sector_externo"]

_MESES = {
    "enero": 1, "febrero": 2, "marzo": 3, "abril": 4, "mayo": 5, "junio": 6,
    "julio": 7, "agosto": 8, "septiembre": 9, "setiembre": 9, "octubre": 10,
    "noviembre": 11, "diciembre": 12,
}


def _strip_accents(s: str) -> str:
    return "".join(
        c for c in unicodedata.normalize("NFKD", s) if not unicodedata.combining(c)
    )


def _slug(s: str) -> str:
    """Accent-insensitive, lowercase, alnum→underscore slug (stable series codes)."""
    out = []
    for ch in _strip_accents(s or "").lower().strip():
        out.append(ch if ch.isalnum() else "_")
    slug = "".join(out)
    while "__" in slug:
        slug = slug.replace("__", "_")
    return slug.strip("_") or "x"


def _period_from_date(ds: str) -> Optional[str]:
    """``"13/05/2026"`` → ``"2026-05"``. None if unparseable."""
    try:
        d, m, y = ds.split("/")
        return f"{int(y):04d}-{int(m):02d}"
    except (ValueError, AttributeError):
        return None


def _period_from_label(s: str) -> Optional[str]:
    """``"Abril 2026"`` → ``"2026-04"``. None for ranges (``"Ene-Abr 2026"``) etc."""
    parts = (s or "").strip().split()
    if len(parts) == 2 and parts[1].isdigit():
        month = _MESES.get(_strip_accents(parts[0]).lower())
        if month:
            return f"{int(parts[1]):04d}-{month:02d}"
    return None


def _num(v: Any) -> Optional[float]:
    if v is None:
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def parse_variable(
    variable: str, payload: Any, lineage: Lineage, default_period: str,
) -> List[Record]:
    """Flatten a BCRD variable's ``{values:[{name, values:[{name,value}], date?}]}``.

    Two group shapes:
      * **value-group** (carries ``date``, or metric names aren't periods): each
        metric is its own series; period = month of ``date`` (else *default_period*).
      * **period-group** (no ``date`` and metric names parse as months, e.g. IMAE):
        the group is the series; period = the metric's month; ranges are skipped.
    """
    out: List[Record] = []
    if not isinstance(payload, dict):
        return out
    for group in payload.get("values") or []:
        if not isinstance(group, dict):
            continue
        gname = group.get("name", "")
        gdate = group.get("date")
        metrics = group.get("values") or []
        parsed_labels = [(_period_from_label(m.get("name", "")), m) for m in metrics]
        is_period_group = (
            not gdate
            and metrics
            and sum(1 for p, _ in parsed_labels if p) >= max(1, len(metrics) // 2)
        )
        if is_period_group:
            code = f"bcrd.{_slug(variable)}.{_slug(gname)}"
            for period, m in parsed_labels:
                if period is None:  # cumulative range / unparseable → skip
                    continue
                out.append(Record(series=code, period=period, value=_num(m.get("value")),
                                   lineage=lineage, unit=None, dimension=gname))
        else:
            period = (_period_from_date(gdate) if gdate else None) or default_period
            for m in metrics:
                code = f"bcrd.{_slug(variable)}.{_slug(gname)}.{_slug(m.get('name', ''))}"
                out.append(Record(series=code, period=period, value=_num(m.get("value")),
                                   lineage=lineage, unit=None, dimension=gname))
    return out


class BCRDClient(FixtureBackedClient):
    source = "BCRD"
    license = "datos oficiales BCRD — uso público con cita"
    license_ok = True
    fixture_file = "bcrd.json"
    live_phase = "Fase 2"

    def __init__(self, mode: str = "fixture", token: str = "", base_url: str = BCRD_BASE_URL):
        super().__init__(mode)  # type: ignore[arg-type]
        self.token = token
        self.base_url = base_url or BCRD_BASE_URL

    def fetch(self, series: Optional[str] = None, period: Optional[str] = None) -> List[Record]:
        self.check_license()
        if self.mode == "live":
            return self._fetch_live(series, period)
        return super().fetch(series, period)

    def _fetch_live(self, series: Optional[str], period: Optional[str]) -> List[Record]:  # pragma: no cover - network I/O
        lineage = Lineage(source=self.source, license=self.license, fetched_at=date.today())
        default_period = date.today().strftime("%Y-%m")
        records: List[Record] = []
        for variable in LIVE_VARIABLES:
            try:
                payload = fetch_bcrd_variable(self.token, variable, base_url=self.base_url)
            except (BcrdApiError, httpx.HTTPError, ValueError) as e:
                logger.warning("[BCRD live] %s falló: %s", variable, e)
                continue
            records.extend(parse_variable(variable, payload, lineage, default_period))
        if series:
            records = [r for r in records if r.series == series]
        if period:
            records = [r for r in records if r.period == period]
        logger.info("[BCRD live] %d observaciones de %d variables", len(records), len(LIVE_VARIABLES))
        return records


bcrd_client = BCRDClient()


def resolve_bcrd_client(db) -> BCRDClient:  # pragma: no cover - thin DB wiring
    """Return a live client when a BCRD token is configured+enabled, else fixture."""
    from shared.settings.service import get_sector_api_base_url, get_sector_api_key

    token = get_sector_api_key(db, "bcrd")
    if token:
        base = get_sector_api_base_url(db, "bcrd") or BCRD_BASE_URL
        return BCRDClient(mode="live", token=token, base_url=base)
    return bcrd_client
