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
    """Parse a metric name that *is* a period.

    ``"Abril 2026"`` → ``"2026-04"``; a bare year ``"2023"`` → ``"2023"`` (annual
    series, e.g. ``sector_externo.cuentas_corrientes``). None for ranges
    (``"Ene-Abr 2026"``) or anything else.
    """
    parts = (s or "").strip().split()
    if len(parts) == 1 and len(parts[0]) == 4 and parts[0].isdigit():
        return parts[0]  # bare year → annual period
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


# ── Human-readable labels for macro series ────────────────────────
# Maps a (slug) ``series_code`` → a Spanish display name + unit. Covers the live
# BCRD series and the legacy fixture series (gdp_growth, …). Anything not listed
# falls back to :func:`humanize_series_code` (slug → readable title).
BCRD_SERIES_LABELS: Dict[str, Dict[str, str]] = {
    # Inflación
    "bcrd.inflacion.inflacion.interanual": {"label": "Inflación interanual", "unit": "%"},
    "bcrd.inflacion.inflacion.acumulada": {"label": "Inflación acumulada", "unit": "%"},
    "bcrd.inflacion.inflacion.mensual": {"label": "Inflación mensual", "unit": "%"},
    "bcrd.inflacion.inflacion_subyacente.interanual": {"label": "Inflación subyacente interanual", "unit": "%"},
    "bcrd.inflacion.inflacion_subyacente.acumulada": {"label": "Inflación subyacente acumulada", "unit": "%"},
    "bcrd.inflacion.inflacion_subyacente.mensual": {"label": "Inflación subyacente mensual", "unit": "%"},
    # Monetarias
    "bcrd.monetarias.tasas_de_interes.activa": {"label": "Tasa de interés activa", "unit": "%"},
    "bcrd.monetarias.tasas_de_interes.pasiva": {"label": "Tasa de interés pasiva", "unit": "%"},
    "bcrd.monetarias.tasas_de_interes.interbancaria": {"label": "Tasa de interés interbancaria", "unit": "%"},
    "bcrd.monetarias.prestamos_privados.total": {"label": "Préstamos al sector privado (total)", "unit": "%"},
    "bcrd.monetarias.prestamos_privados.mon_nacional": {"label": "Préstamos al sector privado (moneda nacional)", "unit": "%"},
    # Sector externo
    "bcrd.sector_externo.reservas_internacionales.brutas": {"label": "Reservas internacionales brutas", "unit": "US$ MM"},
    "bcrd.sector_externo.reservas_internacionales.netas": {"label": "Reservas internacionales netas", "unit": "US$ MM"},
    "bcrd.sector_externo.tasas_de_cambio.compra": {"label": "Tipo de cambio (compra)", "unit": "RD$/US$"},
    "bcrd.sector_externo.tasas_de_cambio.venta": {"label": "Tipo de cambio (venta)", "unit": "RD$/US$"},
    "bcrd.sector_externo.cuentas_corrientes": {"label": "Cuenta corriente", "unit": "% PIB"},
    # Sector real
    "bcrd.sector_real.imaes": {"label": "IMAE (actividad económica)", "unit": "%"},
    "bcrd.sector_real.pibs.producto_interno_bruto": {"label": "Producto Interno Bruto", "unit": "%"},
    "bcrd.sector_real.pibs.pib_anual": {"label": "PIB anual", "unit": "%"},
    # Histórico (backfill desde HistoricoIPC / HistoricoTasas)
    "bcrd.ipc.indice": {"label": "Índice de precios al consumidor (IPC)", "unit": "índice"},
    # Legacy fixture series
    "gdp_growth": {"label": "Crecimiento del PIB", "unit": "%"},
    "inflation_yoy": {"label": "Inflación interanual", "unit": "%"},
    "public_debt_gdp": {"label": "Deuda pública (% PIB)", "unit": "% PIB"},
    "remittances": {"label": "Remesas", "unit": "US$ MM"},
}


def humanize_series_code(code: str) -> str:
    """Derive a readable title from a slug code when no explicit label exists.

    Drops the ``bcrd.`` prefix, splits on ``.``, collapses repeated adjacent
    segments (``inflacion.inflacion`` → ``inflacion``), turns ``_`` into spaces
    and capitalizes. ``bcrd.sector_externo.reservas_internacionales.brutas`` →
    ``"Sector externo · reservas internacionales · brutas"``.
    """
    parts = [p for p in (code or "").split(".") if p]
    if parts and parts[0] == "bcrd":
        parts = parts[1:]
    segments: List[str] = []
    for p in parts:
        seg = p.replace("_", " ").strip()
        if seg and (not segments or segments[-1] != seg):
            segments.append(seg)
    text = " · ".join(segments) or (code or "")
    return text[:1].upper() + text[1:]


def series_label(code: str) -> Dict[str, Optional[str]]:
    """Return ``{"label", "unit"}`` for a series code (explicit map or derived)."""
    entry = BCRD_SERIES_LABELS.get(code)
    if entry:
        return {"label": entry["label"], "unit": entry.get("unit")}
    return {"label": humanize_series_code(code), "unit": None}


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


# ── Historical backfill (HistoricoIPC / HistoricoTasas) ───────────
# Only IPC (monthly since 1984) and exchange rates (daily) expose history via the
# API; the other variables are snapshot-only. Codes are shared with the live
# parser where they line up (FX, inflación interanual) for one continuous series.
IPC_INDEX_SERIES = "bcrd.ipc.indice"
INFLATION_YOY_SERIES = "bcrd.inflacion.inflacion.interanual"
FX_BUY_SERIES = "bcrd.sector_externo.tasas_de_cambio.compra"
FX_SELL_SERIES = "bcrd.sector_externo.tasas_de_cambio.venta"


def _as_item_list(payload: Any) -> List[Any]:
    """Pull the list of records out of a Historico* payload (bare list or wrapped)."""
    if isinstance(payload, list):
        # FX wraps the rows in a single ``{totalCount, items}`` summary object.
        if payload and isinstance(payload[0], dict) and "items" in payload[0]:
            return payload[0].get("items") or []
        return payload
    if isinstance(payload, dict):
        return payload.get("items") or payload.get("values") or payload.get("result") or []
    return []


def parse_ipc_history(payload: Any, lineage: Lineage) -> List[Record]:
    """HistoricoIPC ``[{month, year, indexValue}]`` → IPC index + derived YoY inflation."""
    rows = []
    for it in _as_item_list(payload):
        if not isinstance(it, dict):
            continue
        try:
            y, m = int(it["year"]), int(it["month"])
        except (KeyError, TypeError, ValueError):
            continue
        rows.append((y, m, _num(it.get("indexValue"))))
    rows.sort()
    index_by_ym = {(y, m): v for y, m, v in rows}
    out: List[Record] = []
    for y, m, v in rows:
        period = f"{y:04d}-{m:02d}"
        out.append(Record(series=IPC_INDEX_SERIES, period=period, value=v,
                          lineage=lineage, unit="índice"))
        prev = index_by_ym.get((y - 1, m))
        if prev and v:
            yoy = round((v / prev - 1) * 100, 2)
            out.append(Record(series=INFLATION_YOY_SERIES, period=period, value=yoy,
                              lineage=lineage, unit="%"))
    return out


def parse_fx_history(payload: Any, lineage: Lineage, currency_id: int = 1) -> List[Record]:
    """HistoricoTasas daily rates → month-end buying/selling for *currency_id* (USD=1)."""
    by_period: Dict[str, tuple] = {}  # period → (date, buying, selling)
    for it in _as_item_list(payload):
        if not isinstance(it, dict) or it.get("currencyId") != currency_id or it.get("isDeleted"):
            continue
        ds = (it.get("exchangeRateDate") or "")[:10]  # "2026-06-11"
        if len(ds) < 7:
            continue
        period = ds[:7]
        prev = by_period.get(period)
        if prev is None or ds > prev[0]:  # keep the latest day in the month
            by_period[period] = (ds, _num(it.get("buyingValue")), _num(it.get("sellingValue")))
    out: List[Record] = []
    for period, (_ds, buy, sell) in sorted(by_period.items()):
        out.append(Record(series=FX_BUY_SERIES, period=period, value=buy, lineage=lineage, unit="RD$/US$"))
        out.append(Record(series=FX_SELL_SERIES, period=period, value=sell, lineage=lineage, unit="RD$/US$"))
    return out


def fetch_history(
    token: str, base_url: str, year_from: int, year_to: int,
) -> List[Record]:  # pragma: no cover - network I/O
    """Fetch + parse the full IPC and FX history into Records (for a backfill)."""
    from datetime import date

    lineage = Lineage(source="BCRD", license=BCRDClient.license, fetched_at=date.today())
    records: List[Record] = []
    ipc_extra = {
        "yearFrom": year_from, "monthFrom": 1, "yearTo": year_to, "monthTo": 12,
        "skipCount": 0, "maxResultCount": 100000,
    }
    fx_extra = {
        "fromDate": f"{year_from}-01-01", "toDate": f"{year_to}-12-31",
        "skipCount": 0, "maxResultCount": 100000,
    }
    for variable, extra, parser in (
        ("historico_ipc", ipc_extra, parse_ipc_history),
        ("historico_tasas", fx_extra, parse_fx_history),
    ):
        try:
            payload = fetch_bcrd_variable(token, variable, base_url=base_url, extra=extra)
            records.extend(parser(payload, lineage))
        except (BcrdApiError, httpx.HTTPError, ValueError) as e:
            logger.warning("[BCRD backfill] %s falló: %s", variable, e)
    return records


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
