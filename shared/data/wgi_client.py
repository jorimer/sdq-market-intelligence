"""World Bank Worldwide Governance Indicators (WGI) — live connector.

Feeds the IRMP (Eje 4) *political* dimension's three governance variables, on the
WGI 0-100 percentile-score scale (higher = better governance):

    GOV_WGI_RL.SC → wgi_rule_of_law
    GOV_WGI_GE.SC → wgi_gov_effectiveness
    GOV_WGI_CC.SC → wgi_control_corruption

The legacy ``RL.PER.RNK`` codes were archived; these ``GOV_WGI_*.SC`` codes are
the current ones. Public API (no auth), CC-BY 4.0. The `Record` has no country
field, so the ISO2 country is carried in ``Record.dimension`` (a disaggregation).
"""
import logging
from datetime import date
from typing import Dict, List, Optional, Tuple

import httpx

from shared.data.base_client import FixtureBackedClient, Record
from shared.data.lineage import Lineage

logger = logging.getLogger("sdq.data.wgi")

WGI_BASE_URL = "https://api.worldbank.org/v2"

# WGI indicator code → our IRMP variable name (0-100 governance score).
WGI_INDICATORS: Dict[str, str] = {
    "GOV_WGI_RL.SC": "wgi_rule_of_law",
    "GOV_WGI_GE.SC": "wgi_gov_effectiveness",
    "GOV_WGI_CC.SC": "wgi_control_corruption",
}

# Regional peer set: our ISO2 key → ISO3 (what the WB API expects).
PEER_ISO3: Dict[str, str] = {
    "DO": "DOM", "CR": "CRI", "PA": "PAN", "GT": "GTM", "JM": "JAM",
}
ISO3_TO_ISO2: Dict[str, str] = {v: k for k, v in PEER_ISO3.items()}


class WGIApiError(RuntimeError):
    """The WGI API returned an error or an unparseable shape."""


def fetch_wgi_indicator(
    indicator: str, iso3_codes: List[str], mrv: int = 1, timeout: int = 30,
) -> Tuple[List[dict], Optional[str]]:
    """GET one WGI indicator for the given ISO3 countries.

    Returns ``(rows, last_updated)``. *mrv* = "most recent values" per country
    (handles the publication lag — WGI is annual and ~1 year delayed). Raises
    :class:`WGIApiError` on the API's error shape (``[{"message": [...]}]``).
    """
    url = f"{WGI_BASE_URL}/country/{';'.join(iso3_codes)}/indicator/{indicator}"
    resp = httpx.get(url, params={"format": "json", "mrv": mrv, "per_page": 1000}, timeout=timeout)
    resp.raise_for_status()
    data = resp.json()
    # Error shape: a single-element list whose [0] carries a "message".
    if not isinstance(data, list) or len(data) < 2:
        msg = data[0].get("message") if isinstance(data, list) and data and isinstance(data[0], dict) else data
        raise WGIApiError(f"WGI {indicator}: respuesta inválida del Banco Mundial ({msg})")
    meta = data[0] if isinstance(data[0], dict) else {}
    return (data[1] or []), meta.get("lastupdated")


class WGIClient(FixtureBackedClient):
    source = "WGI"
    license = "World Bank Open Data (CC-BY 4.0)"
    license_ok = True
    fixture_file = "wgi.json"
    live_phase = "Fase 4 (Eje 4)"

    def fetch(self, series: Optional[str] = None, period: Optional[str] = None) -> List[Record]:
        self.check_license()
        if self.mode == "live":
            return self._fetch_live(series, period)
        return self._fetch_fixture(series, period)

    # ── Live ──────────────────────────────────────────────────────
    def _fetch_live(self, series: Optional[str], period: Optional[str]) -> List[Record]:  # pragma: no cover - network I/O
        iso3 = list(PEER_ISO3.values())
        out: List[Record] = []
        for code, var in WGI_INDICATORS.items():
            try:
                rows, last_updated = fetch_wgi_indicator(code, iso3)
            except (WGIApiError, httpx.HTTPError, ValueError) as e:
                logger.warning("[WGI live] %s falló: %s", code, e)
                continue
            published = _parse_date(last_updated)
            for r in rows:
                out.append(self._row_to_record(r, var, code, published))
        return _filter(out, series, period)

    def _row_to_record(self, row: dict, var: str, code: str, published: Optional[date]) -> Record:
        iso3 = row.get("countryiso3code") or ""
        year = row.get("date")
        val = row.get("value")
        lineage = Lineage(
            source=self.source, license=self.license,
            published_at=published, fetched_at=date.today(),
            url=f"{WGI_BASE_URL}/country/{iso3}/indicator/{code}",
            note="WGI anual; rezago de publicación ~1 año",
        )
        return Record(
            series=var,
            period=str(year) if year else "",
            value=None if val is None else float(val),
            lineage=lineage,
            unit="percentil 0-100",
            dimension=ISO3_TO_ISO2.get(iso3, iso3),  # country carried here
        )

    # ── Fixture (offline) ─────────────────────────────────────────
    def _fetch_fixture(self, series: Optional[str], period: Optional[str]) -> List[Record]:
        """Fixture shape: ``{"<iso2>": {"<var>": {"<year>": value}}}``."""
        fixture = self._load_fixture(self.fixture_file)
        lineage = Lineage(source=self.source, license=self.license, fetched_at=date.today())
        out: List[Record] = []
        for iso2, vars_ in fixture.items():
            for var, obs in vars_.items():
                for yr, val in obs.items():
                    out.append(Record(
                        series=var, period=str(yr),
                        value=None if val is None else float(val),
                        lineage=lineage, unit="percentil 0-100", dimension=iso2,
                    ))
        return _filter(out, series, period)


def _filter(records: List[Record], series: Optional[str], period: Optional[str]) -> List[Record]:
    if series:
        records = [r for r in records if r.series == series]
    if period:
        records = [r for r in records if r.period == period]
    return records


def _parse_date(s: Optional[str]) -> Optional[date]:
    if not s:
        return None
    try:
        return date.fromisoformat(s[:10])
    except ValueError:
        return None


wgi_client = WGIClient()
