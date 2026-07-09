"""DGA trade by PARTNER COUNTRY — quarterly exports/imports FOB, from Power BI.

The DGA (Dirección General de Aduanas) publishes *Comercio Exterior* only through a
Power BI *publish to web* dashboard. The by-HS-chapter file feeds
:mod:`modules.trade_intel.dga_sync`; this connector adds the **geographic** cut the
chapter files omit — trade value by partner country, per quarter, both directions —
by querying the dashboard's semantic model directly (same recipe as
:mod:`shared.data.tss_salary`, shared plumbing in :mod:`shared.data.powerbi`).

Model (verified 2026-07-09): fact ``Fac_DBComercio`` (``Flujo``/``FOB``/``Pais``);
FOB is a *column*, so the value is aggregated by the DAX measures ``Total Fob Exp``
and ``Total Fob Imp`` in ``DAX_Medidas``. Partner names come from ``Dim_Paises``
(``Nombre``), the period from ``Dim_Calendario`` (``Año`` × ``NoTrimestre``).
Granularity: annual 2016→, quarterly + monthly 2016→2026-05.

``live`` mode hits the anonymous data API and returns the last
:data:`KEEP_QUARTERS` quarters (top :data:`TOP_PARTNERS` partners per flow); the
report's DSR encodes some numerics as strings → coerced. Values are FOB **USD**.
``fixture`` mode reads the committed real snapshot (``dga_partners.json``). Fails
**closed**: any network/structural surprise raises :class:`DGAPartnersError`, never
fabricated data. Missing values stay ``None``.
"""
import logging
from datetime import date
from typing import Dict, List, Optional

from shared.data import powerbi
from shared.data.base_client import FixtureBackedClient, Record
from shared.data.lineage import Lineage

logger = logging.getLogger("sdq.data.dga_partners")

# Public Power BI "publish to web" report (DGA · Comercio Exterior). The token
# embeds {k: resourceKey, t: tenant, c: cluster}; k is stable until DGA republishes.
VIEW_TOKEN = (
    "eyJrIjoiYWU4YmRiZjAtZDY4Yy00MDJhLTkwNzctZmFmZGQwOGMyMmMyIiwidCI6IjAwOTgzZGJm"
    "LTgxMzgtNDAyMi05MDIxLWU2YTU0NmMxNzZlMyIsImMiOjF9"
)
VIEW_URL = "https://app.powerbi.com/view?r=" + VIEW_TOKEN

# Model entities / fields (from the conceptualschema).
DIM_PAIS = "Dim_Paises"
DIM_CAL = "Dim_Calendario"
MEAS = "DAX_Medidas"
PARTNER_PROP = "Nombre"          # Dim_Paises: resolved country name
YEAR_PROP = "Año"                # Dim_Calendario
QUARTER_PROP = "NoTrimestre"     # Dim_Calendario: 1..4
MEASURE_EXP = "Total Fob Exp"    # DAX measure (FOB is a column, aggregate via measure)
MEASURE_IMP = "Total Fob Imp"

SERIES = "dga.trade.partner"
UNIT = "USD"
SOURCE = "DGA (Power BI)"
LICENSE = "datos públicos DGA/Aduanas RD — uso con cita"

# Snapshot scope: the connector returns the most recent quarters, top partners per
# flow, so the fixture stays a compact-but-representative real sample.
KEEP_QUARTERS = 8
TOP_PARTNERS = 30
MIN_YEAR = 2024                  # querydata Año >= this (covers the window with margin)
MIN_PARTNERS = 10                # below this the report structure changed → fail closed
# El conceptualschema de ESTE reporte exige modelId ("Both ModelIds and ModelObjectIds are
# empty") — un círculo vicioso (a diferencia del de TSS, que lo devuelve sin args). El
# modelId es estable junto con el token (ambos cambian si la DGA republica → fail-closed →
# fixture). Se intenta descubrirlo por conceptualschema y, si falla, se usa este conocido.
KNOWN_MODEL_ID = 317763


class DGAPartnersError(powerbi.PowerBIError):
    """The DGA Power BI report was unreachable or structurally changed."""


def _to_float(v: object) -> Optional[float]:
    """Coerce a DSR cell to float (the report encodes some numerics as strings)."""
    if v is None:
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def build_query(model_id: int) -> dict:
    """querydata body: partner × año × trimestre with the exp/imp FOB measures."""
    def col(entity_alias: str, prop: str) -> dict:
        return {"Column": {"Expression": {"SourceRef": {"Source": entity_alias}},
                           "Property": prop}}

    def measure(prop: str) -> dict:
        return {"Measure": {"Expression": {"SourceRef": {"Source": "m"}}, "Property": prop}}

    return {
        "version": "1.0.0",
        "queries": [{
            "Query": {"Commands": [{"SemanticQueryDataShapeCommand": {
                "Query": {
                    "Version": 2,
                    "From": [
                        {"Name": "p", "Entity": DIM_PAIS, "Type": 0},
                        {"Name": "c", "Entity": DIM_CAL, "Type": 0},
                        {"Name": "m", "Entity": MEAS, "Type": 0},
                    ],
                    "Select": [
                        {**col("p", PARTNER_PROP), "Name": "p." + PARTNER_PROP},
                        {**col("c", YEAR_PROP), "Name": "c." + YEAR_PROP},
                        {**col("c", QUARTER_PROP), "Name": "c." + QUARTER_PROP},
                        {**measure(MEASURE_EXP), "Name": "m.exp"},
                        {**measure(MEASURE_IMP), "Name": "m.imp"},
                    ],
                    "Where": [
                        {"Condition": {"Comparison": {
                            "ComparisonKind": 2,  # >=
                            "Left": {"Column": {"Expression": {"SourceRef": {"Source": "c"}},
                                                "Property": YEAR_PROP}},
                            "Right": {"Literal": {"Value": f"{MIN_YEAR}L"}},
                        }}},
                    ],
                },
                "Binding": {
                    "Primary": {"Groupings": [{"Projections": [0, 1, 2, 3, 4]}]},
                    "DataReduction": {"DataVolume": 4, "Primary": {"Window": {"Count": 30000}}},
                    "Version": 1,
                },
            }}]},
            "QueryId": "",
            "ApplicationContext": {"DatasetId": "x", "Sources": [{"ReportId": "x"}]},
        }],
        "cancelQueries": [],
        "modelId": model_id,
    }


def _quarter_key(year: int, quarter: int) -> str:
    return f"{year}-Q{quarter}"


def rows_to_records(
    decoded: List[List[object]],
    *,
    keep_quarters: int = KEEP_QUARTERS,
    top_partners: int = TOP_PARTNERS,
    min_partners: int = MIN_PARTNERS,
    published_at: Optional[date] = None,
) -> List[Record]:
    """Turn decoded ``[partner, year, quarter, exp, imp]`` rows into Records.

    Keeps the most recent *keep_quarters* quarters and, within each quarter and
    direction, the *top_partners* partners by value. Fails closed if too few
    partners survive (the report shape changed).
    """
    lineage = Lineage(
        source=SOURCE, license=LICENSE, fetched_at=date.today(), url=VIEW_URL,
        published_at=published_at,
        note="Comercio exterior por país socio (FOB USD, Power BI · Comercio Exterior)",
    )
    # {(period, direction): {partner: value}}
    grouped: Dict[str, Dict[str, Dict[str, float]]] = {}
    for row in decoded:
        if len(row) < 5:
            continue
        partner = row[0]
        year, quarter = row[1], row[2]
        if partner is None or year is None or quarter is None:
            continue
        try:
            period = _quarter_key(int(year), int(quarter))
        except (TypeError, ValueError):
            continue
        exp, imp = _to_float(row[3]), _to_float(row[4])
        bucket = grouped.setdefault(period, {"export": {}, "import": {}})
        if exp is not None:
            bucket["export"][str(partner)] = bucket["export"].get(str(partner), 0.0) + exp
        if imp is not None:
            bucket["import"][str(partner)] = bucket["import"].get(str(partner), 0.0) + imp

    if not grouped:
        raise DGAPartnersError("el reporte DGA no devolvió filas de comercio por país")

    periods = sorted(grouped, key=_period_sort_key)[-keep_quarters:]
    out: List[Record] = []
    partners_seen = set()
    for period in periods:
        for direction in ("export", "import"):
            flows = grouped[period][direction]
            top = sorted(flows.items(), key=lambda kv: kv[1], reverse=True)[:top_partners]
            for partner, value in top:
                partners_seen.add(partner)
                out.append(Record(
                    series=SERIES, period=period, value=round(value, 2),
                    lineage=lineage, unit=UNIT, dimension=f"{direction}:{partner}",
                ))
    if len(partners_seen) < min_partners:
        raise DGAPartnersError(
            f"solo {len(partners_seen)} países socios en el reporte DGA "
            f"(esperados ≥{min_partners}) — ¿cambió la estructura del Power BI?"
        )
    return out


def _period_sort_key(period: str) -> tuple:
    year, quarter = period.split("-Q")
    return (int(year), int(quarter))


def parse_dimension(dimension: str) -> tuple:
    """``"export:Estados Unidos"`` → ``("export", "Estados Unidos")``."""
    direction, _, partner = dimension.partition(":")
    return direction, partner


class DGAPartnersClient(FixtureBackedClient):
    """DGA trade-by-partner-country connector (quarterly, both directions)."""

    source = SOURCE
    license = LICENSE
    license_ok = True
    fixture_file = "dga_partners.json"
    live_phase = "F1 (comercio por país · Power BI live)"

    def fetch(self, series: Optional[str] = None, period: Optional[str] = None) -> List[Record]:
        self.check_license()
        if self.mode == "live":
            return _filter(self._fetch_live(), series, period)
        return _filter(self._fetch_fixture(), series, period)

    # ── Live (Power BI anonymous data API) ────────────────────────
    def _fetch_live(self) -> List[Record]:  # pragma: no cover - network I/O
        import httpx

        res_key = powerbi.resource_key(VIEW_TOKEN)
        # Fail CLOSED de verdad: cualquier sorpresa de red/estructura (incluido el
        # HTTPStatusError de httpx, p.ej. el conceptualschema de la DGA que exige modelId
        # y a veces 400ea) se envuelve en DGAPartnersError para que el sync pueda decidir
        # (cae al fixture real commiteado) en vez de propagar un error crudo.
        try:
            api = powerbi.resolve_api_host(VIEW_URL)
            with httpx.Client(http2=False, timeout=90, headers=powerbi.browser_headers()) as client:
                # El conceptualschema de la DGA exige modelId (ver KNOWN_MODEL_ID); se intenta
                # igual (por si el reporte pasa a soportarlo) y si falla se usa el conocido.
                try:
                    model_id = powerbi.fetch_model_id(client, api, res_key)
                except Exception:  # noqa: BLE001
                    model_id = KNOWN_MODEL_ID
                resp = client.post(
                    f"{api}/public/reports/querydata?synchronous=true",
                    headers=powerbi.api_headers(res_key),
                    json=build_query(model_id),
                )
                resp.raise_for_status()
                decoded = powerbi.decode_dsr_rows(resp.json(), min_cols=5)
            return rows_to_records(decoded)
        except DGAPartnersError:
            raise
        except Exception as e:  # noqa: BLE001 — normalizar a fail-closed
            raise DGAPartnersError(f"extracción live de la DGA falló: {e}") from e

    # ── Fixture (offline / tests) ─────────────────────────────────
    def _fetch_fixture(self) -> List[Record]:
        """Fixture shape: ``{"<period>": {"export": {partner: v}, "import": {...}}}``."""
        fixture = self._load_fixture(self.fixture_file)
        lineage = Lineage(source=self.source, license=self.license, fetched_at=date.today())
        out: List[Record] = []
        for period, dirs in fixture.items():
            if period.startswith("_"):
                continue
            for direction in ("export", "import"):
                for partner, val in (dirs.get(direction) or {}).items():
                    out.append(Record(
                        series=SERIES, period=period,
                        value=None if val is None else float(val),
                        lineage=lineage, unit=UNIT, dimension=f"{direction}:{partner}",
                    ))
        return out


def _filter(records: List[Record], series: Optional[str], period: Optional[str]) -> List[Record]:
    if series:
        records = [r for r in records if r.series == series]
    if period:
        records = [r for r in records if r.period == period]
    return records


dga_partners_client = DGAPartnersClient()
