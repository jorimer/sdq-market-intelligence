"""GDELT DOC 2.0 — live connector for the IRMP events dimension.

Sources two of the three events-dimension inputs from GDELT's free DOC 2.0 API
(no auth, but rate-limited to ~1 req/5s — the sync paces requests with retries):

  news_sentiment  ← average tone of recent coverage mentioning the country
  unrest_shocks   ← share of the country's coverage that is protest/unrest-related

``sanctions_signal`` stays a declared rubric (doctrine) — too sparse/noisy for
these peers to source reliably. A missing/failed signal stays ``None`` so the
declared rubric value is used downstream — never fabricated. The country is
carried in ``Record.dimension`` (the DOC API has no country field).
"""
import logging
import time
from datetime import date
from typing import Dict, List, Optional

import httpx

from shared.data.base_client import FixtureBackedClient, Record
from shared.data.lineage import Lineage

logger = logging.getLogger("sdq.data.gdelt")

GDELT_DOC_URL = "https://api.gdeltproject.org/api/v2/doc/doc"

# Regional peer set: our ISO2 key → the GDELT free-text country query.
PEER_QUERY: Dict[str, str] = {
    "DO": "Dominican Republic", "CR": "Costa Rica", "PA": "Panama",
    "GT": "Guatemala", "JM": "Jamaica",
}
UNREST_TERMS = "(protest OR unrest OR riot OR strike OR violence OR crisis)"

RATE_DELAY = 8.0       # seconds between requests (GDELT limit ~1/5s; be gentle)
_MAX_RETRIES = 2       # few retries — hammering a rate-limited IP makes it worse
TIMESPAN = "1month"


class GDELTApiError(RuntimeError):
    """GDELT returned a rate-limit notice or an unparseable shape."""


def get_timeline(query: str, mode: str, timeout: int = 30) -> List[float]:
    """GET a DOC timeline; return the series' values (empty list on no data).

    Retries on the plain-text rate-limit notice (sleeping between tries). Raises
    :class:`GDELTApiError` if it never returns JSON.
    """
    params = {"query": query, "mode": mode, "format": "json", "timespan": TIMESPAN}
    last = ""
    for attempt in range(_MAX_RETRIES):
        resp = httpx.get(GDELT_DOC_URL, params=params, timeout=timeout,
                         headers={"User-Agent": "Mozilla/5.0 (SDQ-MIP)"})
        text = resp.text or ""
        if text.lstrip().startswith("{"):
            data = resp.json()
            tl = data.get("timeline") or []
            series = tl[0].get("data") if tl else []
            return [p["value"] for p in series if p.get("value") is not None]
        last = text.strip()[:80]
        time.sleep(RATE_DELAY * (attempt + 1))
    raise GDELTApiError(f"GDELT {mode}: sin JSON tras reintentos ({last})")


def _avg(vals: List[float]) -> Optional[float]:
    return round(sum(vals) / len(vals), 3) if vals else None


def unrest_ratio(protest_avg: Optional[float], total_avg: Optional[float]) -> Optional[float]:
    """Share (0-100) of a country's coverage that is protest/unrest-related.

    Normalizes for country media footprint (protest volume ÷ total volume), so a
    bigger country isn't flagged just for having more coverage. ``None`` when the
    inputs are missing or total coverage is ~0 — never fabricated.
    """
    if protest_avg is None or not total_avg or total_avg <= 0:
        return None
    return round(min(100.0, 100.0 * protest_avg / total_avg), 2)


class GDELTClient(FixtureBackedClient):
    source = "GDELT"
    license = "GDELT Project (open data)"
    license_ok = True
    fixture_file = "gdelt.json"
    live_phase = "Fase 4 (Eje 4 · eventos)"

    def fetch(self, series: Optional[str] = None, period: Optional[str] = None) -> List[Record]:
        self.check_license()
        if self.mode == "live":
            return self._fetch_live(series, period)
        return self._fetch_fixture(series, period)

    # ── Live (paced; network I/O) ─────────────────────────────────
    def _fetch_live(self, series: Optional[str], period: Optional[str]) -> List[Record]:  # pragma: no cover - network I/O
        out: List[Record] = []
        for iso2, name in PEER_QUERY.items():
            q = f'"{name}"'
            try:
                tone = _avg(get_timeline(q, "timelinetone"))
            except (GDELTApiError, httpx.HTTPError, ValueError) as e:
                logger.warning("[GDELT] tono %s falló: %s", iso2, e)
                tone = None
            time.sleep(RATE_DELAY)
            unrest = None
            try:
                protest = _avg(get_timeline(f"{q} {UNREST_TERMS}", "timelinevol"))
                time.sleep(RATE_DELAY)
                total = _avg(get_timeline(q, "timelinevol"))
                unrest = unrest_ratio(protest, total)
            except (GDELTApiError, httpx.HTTPError, ValueError) as e:
                logger.warning("[GDELT] disturbios %s falló: %s", iso2, e)
            time.sleep(RATE_DELAY)
            out.append(self._record("news_sentiment", tone, iso2, "tono GDELT (−100..100)"))
            out.append(self._record("unrest_shocks", unrest, iso2, "% de cobertura de disturbios"))
        return _filter(out, series, period)

    def _record(self, var: str, value: Optional[float], iso2: str, unit: str) -> Record:
        lineage = Lineage(
            source=self.source, license=self.license, fetched_at=date.today(),
            url=GDELT_DOC_URL, note=f"GDELT DOC 2.0, ventana {TIMESPAN}",
        )
        return Record(
            series=var, period=str(date.today().year),
            value=None if value is None else float(value),
            lineage=lineage, unit=unit, dimension=iso2,
        )

    # ── Fixture (offline / tests) ─────────────────────────────────
    def _fetch_fixture(self, series: Optional[str], period: Optional[str]) -> List[Record]:
        fixture = self._load_fixture(self.fixture_file)
        lineage = Lineage(source=self.source, license=self.license, fetched_at=date.today())
        out: List[Record] = []
        for iso2, vars_ in fixture.items():
            for var, obs in vars_.items():
                for yr, val in obs.items():
                    out.append(Record(
                        series=var, period=str(yr),
                        value=None if val is None else float(val),
                        lineage=lineage, unit=None, dimension=iso2,
                    ))
        return _filter(out, series, period)


def _filter(records: List[Record], series: Optional[str], period: Optional[str]) -> List[Record]:
    if series:
        records = [r for r in records if r.series == series]
    if period:
        records = [r for r in records if r.period == period]
    return records


gdelt_client = GDELTClient()
