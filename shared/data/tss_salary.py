"""TSS average salary by economic activity — the IAI ``operating_cost`` source.

Pulls the *salario promedio cotizable por actividad económica* the TSS (Tesorería
de la Seguridad Social) publishes in its public Power BI "publish to web" report
(*Cotizaciones*), the only open channel for this figure after the 2025/2026 site
redesign retired the stable PDF URLs. The report's ``ACT_ECO2_BC`` field carries
18 detailed activities — finer than the ONE/ENCFT employment branches (it separates
minería, transporte, comunicaciones, enseñanza, salud, inmobiliario) — which
:mod:`shared.data.sector_crosswalk` maps to the BCRD-17 slugs.

The salary is a CROSS-SECTIONAL input (it discriminates sectors, applied uniformly
across periods like the national WGI), so the connector takes the most recent
years; one good snapshot is enough.

Extraction (verified 2026-06-19): the Power BI anonymous data API. The view token
embeds the resource key; the data host is the report's ``-api`` cluster (NOT the
``-redirect`` one, which 403s); ``conceptualschema`` gives the model id and
``querydata`` returns a compressed DSR that :func:`decode_dsr` reconstructs. This
is an undocumented internal API — fragile by nature — so the live path fails closed
(raises :class:`TSSSalaryError`) and stamps provenance; offline/tests read the
committed ``tss_salary.json`` snapshot. Missing values stay ``None``.
"""
import json
import logging
import re
import uuid
from datetime import date
from typing import Dict, List, Optional, Tuple

from shared.data._text import norm
from shared.data.base_client import FixtureBackedClient, Record
from shared.data.lineage import Lineage

logger = logging.getLogger("sdq.data.tss_salary")

# Public Power BI "publish to web" report (TSS · Cotizaciones). The token embeds
# {k: resourceKey, t: tenant, c: cluster}; k is stable until the TSS republishes.
VIEW_TOKEN = (
    "eyJrIjoiMWEyZGMyZmYtNWI5Yy00MjE1LWIxZWEtNDYzN2JlNzkyZmUxIiwidCI6IjY1OGYzMW"
    "Y0LTg5YjEtNDJlMC1iYWNlLWYzMTkwNDBkZmRmOSIsImMiOjF9"
)
VIEW_URL = "https://app.powerbi.com/view?r=" + VIEW_TOKEN
ENTITY = "Query1"
ACTIVITY_PROP = "ACT_ECO2_BC"     # detailed activity (18); the plain field is 3 broad sectors
YEAR_PROP = "Año"
SALARY_PROP = "Salario Promedio (RD$)"
DROP_ACTIVITY = "no_identificado"  # the residual bucket (activity_key form) — not a sector

VAR_SALARY = "avg_salary"
UNIT_SALARY = "RD$/mes (salario promedio cotizable)"
LICENSE = "datos públicos TSS/SDSS — uso con cita"
MIN_ACTIVITIES = 15   # below this the report structure changed → fail closed
_HEADERS = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                          "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"}


class TSSSalaryError(RuntimeError):
    """The TSS Power BI report was unreachable or structurally changed."""


def activity_key(label: object) -> str:
    """Stable key for a TSS activity label (accent/case-insensitive, snake_case).

    NOTE: a key can exceed 40 chars (e.g.
    ``intermediacion_financiera_seguros_y_otras`` = 41). These keys are the raw
    connector dimension; do NOT persist them in ``SectorVariable.sector_code``
    (``String(40)`` → silent truncation on Postgres). Downstream wiring must map to
    the BCRD-17 slugs via :func:`shared.data.sector_crosswalk.salary_by_slug` first.
    """
    return re.sub(r"[^a-z0-9]+", "_", norm(label)).strip("_")


# ── DSR decoding (pure) ───────────────────────────────────────────────────────
def decode_dsr(response: dict) -> List[Tuple[str, str, Optional[float]]]:
    """Decode a Power BI querydata DSR → ``[(activity_label, year, salary)]``.

    The DSR packs a matrix with per-column value dictionaries (``ValueDicts``) and
    a row list (``DM0``) where each row carries only the columns that changed: ``C``
    holds present values (a dict index for dimension columns, a literal for the
    measure), ``R`` is a bitmask of columns reused from the previous row, ``Ø`` a
    bitmask of nulls. Pure of network — unit-testable against a fixed payload.
    """
    try:
        dsr = response["results"][0]["result"]["data"]["dsr"]
    except (KeyError, IndexError, TypeError) as e:
        raise TSSSalaryError(f"DSR inesperado de Power BI: {str(response)[:200]}") from e
    if "DS" not in dsr:
        # Power BI returns an odata error (e.g. a bad measure reference) under
        # DataShapes instead of DS — surface it explicitly, fail closed.
        try:
            msg = dsr["DataShapes"][0]["odata.error"]["message"]["value"]
        except (KeyError, IndexError, TypeError):
            msg = str(dsr)[:200]
        raise TSSSalaryError(f"Power BI rechazó la consulta TSS: {msg}")
    ds = dsr["DS"][0]
    dicts = ds.get("ValueDicts", {})
    rows = ds.get("PH", [{}])[0].get("DM0", [])
    if not rows:
        return []
    # column → value dict name (D0/D1/…) from the first row's select descriptor;
    # a column with no ``DN`` is the measure (literal value, no dict).
    col_dict: Dict[int, Optional[str]] = {}
    for i, s in enumerate(rows[0].get("S", [])):
        col_dict[i] = s.get("DN")
    ncols = len(col_dict)
    if ncols < 3:
        # the first row must carry the select descriptor (activity, year, measure)
        raise TSSSalaryError("DSR sin descriptor de columnas (S) — el reporte TSS cambió")
    out: List[Tuple[str, str, Optional[float]]] = []
    prev: List[object] = [None] * ncols
    for r in rows:
        c = r.get("C", [])
        reuse = r.get("R", 0)
        nulls = r.get("Ø", 0)
        vals: List[object] = []
        ci = 0
        for col in range(ncols):
            if reuse & (1 << col):
                vals.append(prev[col])
            elif nulls & (1 << col):
                vals.append(None)
            else:
                vals.append(c[ci] if ci < len(c) else None)
                ci += 1
        prev = vals[:]
        # resolve dict-backed columns to their labels
        resolved = []
        for col in range(ncols):
            v = vals[col]
            dn = col_dict.get(col)
            if dn and isinstance(v, int) and dn in dicts and 0 <= v < len(dicts[dn]):
                resolved.append(dicts[dn][v])
            else:
                resolved.append(v)
        activity, year = str(resolved[0]), str(resolved[1])
        sal = resolved[2]
        out.append((activity, year, None if sal is None else float(sal)))
    return out


def build_query(model_id: int) -> dict:
    """The querydata body: salary by ``ACT_ECO2_BC`` × ``Año`` (Version-2 semantic)."""
    def col(prop):
        return {"Column": {"Expression": {"SourceRef": {"Source": "q"}}, "Property": prop}}

    return {
        "version": "1.0.0",
        "queries": [{
            "Query": {"Commands": [{"SemanticQueryDataShapeCommand": {
                "Query": {
                    "Version": 2,
                    "From": [{"Name": "q", "Entity": ENTITY, "Type": 0}],
                    "Select": [
                        {**col(ACTIVITY_PROP), "Name": "q." + ACTIVITY_PROP},
                        {**col(YEAR_PROP), "Name": "q." + YEAR_PROP},
                        {"Measure": {"Expression": {"SourceRef": {"Source": "q"}},
                         "Property": SALARY_PROP}, "Name": "q.salary"},
                    ],
                },
                "Binding": {
                    "Primary": {"Groupings": [{"Projections": [0, 1, 2]}]},
                    "DataReduction": {"DataVolume": 4, "Primary": {"Window": {"Count": 2000}}},
                    "Version": 1,
                },
            }}]},
            "QueryId": "",
            "ApplicationContext": {"DatasetId": "x", "Sources": [{"ReportId": "x"}]},
        }],
        "cancelQueries": [],
        "modelId": model_id,
    }


def build_salary_records(
    decoded: List[Tuple[str, str, Optional[float]]],
    *,
    published_at: Optional[date] = None,
) -> List[Record]:
    """Turn decoded ``(activity, year, salary)`` rows into per-activity Records.

    Drops the residual ``No identificado`` bucket. Fail-closed if fewer than
    :data:`MIN_ACTIVITIES` distinct activities survive (the report changed shape).
    """
    lineage = Lineage(
        source="TSS", license=LICENSE, fetched_at=date.today(), url=VIEW_URL,
        published_at=published_at,
        note="Salario promedio cotizable por actividad económica (Power BI · Cotizaciones)",
    )
    out: List[Record] = []
    activities = set()
    for activity, year, salary in decoded:
        key = activity_key(activity)
        if not key or key == DROP_ACTIVITY:
            continue
        if not re.fullmatch(r"\d{4}", year):
            continue
        activities.add(key)
        out.append(Record(series=VAR_SALARY, period=year, value=salary,
                           lineage=lineage, unit=UNIT_SALARY, dimension=key))
    if len(activities) < MIN_ACTIVITIES:
        raise TSSSalaryError(
            f"solo {len(activities)} actividades en el reporte TSS "
            f"(esperadas ≥{MIN_ACTIVITIES}) — ¿cambió la estructura del Power BI?"
        )
    return out


def _filter(records: List[Record], series: Optional[str], period: Optional[str]) -> List[Record]:
    if series:
        records = [r for r in records if r.series == series]
    if period:
        records = [r for r in records if r.period == period]
    return records


class TSSSalaryClient(FixtureBackedClient):
    """TSS average salary by activity (IAI ``operating_cost`` source)."""

    source = "TSS"
    license = LICENSE
    license_ok = True
    fixture_file = "tss_salary.json"
    live_phase = "Fase 4 (Eje 3 · costo operativo)"

    def fetch(self, series: Optional[str] = None, period: Optional[str] = None) -> List[Record]:
        self.check_license()
        if self.mode == "live":
            return self._fetch_live(series, period)
        return self._fetch_fixture(series, period)

    # ── Live (Power BI anonymous data API) ────────────────────────
    def _fetch_live(self, series: Optional[str], period: Optional[str]) -> List[Record]:  # pragma: no cover - network I/O
        import httpx

        resource_key = json.loads(_b64(VIEW_TOKEN))["k"]
        api = self._resolve_api_host()
        with httpx.Client(http2=False, timeout=40, headers=_HEADERS) as client:
            model_id = self._model_id(client, api, resource_key)
            resp = client.post(
                f"{api}/public/reports/querydata?synchronous=true",
                headers=self._api_headers(resource_key),
                json=build_query(model_id),
            )
            resp.raise_for_status()
            decoded = decode_dsr(resp.json())
        records = build_salary_records(decoded)
        return _filter(records, series, period)

    def _resolve_api_host(self) -> str:  # pragma: no cover - network I/O
        """Resolve the report's data cluster from the view page, fail-closed."""
        import httpx

        r = httpx.get(VIEW_URL, timeout=30, follow_redirects=True, headers=_HEADERS)
        r.raise_for_status()
        m = re.search(r"https://(wabi-[a-z0-9-]+-redirect)\.analysis\.windows\.net", r.text)
        if not m:
            raise TSSSalaryError("no se pudo resolver el cluster del reporte Power BI TSS")
        # the data host is the same cluster with "-redirect" swapped for "-api".
        host = m.group(1).replace("-redirect", "-api")
        return f"https://{host}.analysis.windows.net"

    @staticmethod
    def _api_headers(resource_key: str) -> Dict[str, str]:
        return {
            **_HEADERS,
            "Accept": "application/json, text/plain, */*",
            "X-PowerBI-ResourceKey": resource_key,
            "Content-Type": "application/json;charset=UTF-8",
            "ActivityId": str(uuid.uuid4()),
            "RequestId": str(uuid.uuid4()),
            "Origin": "https://app.powerbi.com",
            "Referer": "https://app.powerbi.com/",
        }

    def _model_id(self, client, api: str, resource_key: str) -> int:  # pragma: no cover - network I/O
        resp = client.post(
            f"{api}/public/reports/conceptualschema",
            headers=self._api_headers(resource_key),
            json={"version": "1.0.0", "queryApiVersion": 2, "resourceKey": resource_key},
        )
        resp.raise_for_status()
        schemas = resp.json().get("schemas", [])
        if not schemas or "modelId" not in schemas[0]:
            raise TSSSalaryError("conceptualschema sin modelId — el reporte TSS cambió")
        return schemas[0]["modelId"]

    # ── Fixture (offline / tests) ─────────────────────────────────
    def _fetch_fixture(self, series: Optional[str], period: Optional[str]) -> List[Record]:
        """Fixture shape: ``{"<activity_key>": {"avg_salary": {"<year>": value}}}``."""
        fixture = self._load_fixture(self.fixture_file)
        lineage = Lineage(source=self.source, license=self.license, fetched_at=date.today())
        out: List[Record] = []
        for key, vars_ in fixture.items():
            for var, obs in vars_.items():
                for yr, val in obs.items():
                    out.append(Record(
                        series=var, period=str(yr),
                        value=None if val is None else float(val),
                        lineage=lineage, unit=UNIT_SALARY, dimension=key,
                    ))
        return _filter(out, series, period)


def _b64(token: str) -> bytes:
    import base64
    return base64.b64decode(token + "=" * (-len(token) % 4))


tss_salary_client = TSSSalaryClient()
