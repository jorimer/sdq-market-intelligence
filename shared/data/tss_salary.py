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
import logging
import re
from datetime import date
from typing import Dict, List, Optional, Tuple

from shared.data import powerbi
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


class TSSSalaryError(powerbi.PowerBIError):
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

    Thin adapter over :func:`shared.data.powerbi.decode_dsr_rows` (the shared,
    source-agnostic decoder) that projects each 3-column row to the TSS shape.
    The report must carry activity, year and the salary measure → ``min_cols=3``.
    """
    try:
        rows = powerbi.decode_dsr_rows(response, min_cols=3)
    except powerbi.PowerBIError as e:
        # keep the historical TSS-flavoured wording (rechazó / descriptor)
        msg = str(e).replace("Power BI rechazó la consulta", "Power BI rechazó la consulta TSS")
        msg = msg.replace("el reporte cambió", "el reporte TSS cambió")
        raise TSSSalaryError(msg) from e
    out: List[Tuple[str, str, Optional[float]]] = []
    for resolved in rows:
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

        res_key = powerbi.resource_key(VIEW_TOKEN)
        api = powerbi.resolve_api_host(VIEW_URL)
        with httpx.Client(http2=False, timeout=40, headers=powerbi.browser_headers()) as client:
            model_id = powerbi.fetch_model_id(client, api, res_key)
            resp = client.post(
                f"{api}/public/reports/querydata?synchronous=true",
                headers=powerbi.api_headers(res_key),
                json=build_query(model_id),
            )
            resp.raise_for_status()
            decoded = decode_dsr(resp.json())
        records = build_salary_records(decoded)
        return _filter(records, series, period)

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


tss_salary_client = TSSSalaryClient()
