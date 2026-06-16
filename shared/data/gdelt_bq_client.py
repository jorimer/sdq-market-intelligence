"""GDELT via BigQuery — robust connector for the IRMP events dimension.

Queries the GDELT public dataset (``gdelt-bq.gdeltv2.gkg_partitioned``) instead of
the rate-limited DOC API. One partition-pruned, column-pruned query yields all
three events-dimension inputs for the peer set:

  news_sentiment   ← AVG(V2Tone) of coverage mentioning the country
  unrest_shocks    ← % of the country's records flagged with a PROTEST theme
  sanctions_signal ← % flagged with an ECON_SANCTIONS theme

Cost stays inside BigQuery's 1 TB/month free tier: partition filter on
``_PARTITIONTIME`` + selecting only V2Tone/V2Themes/V2Locations. Credentials come
from the ``GCP_SA_JSON`` env var (service-account JSON, set by the owner in
Railway) — never handled in code/plaintext here. Missing/failed → empty, so the
declared rubric remains the fallback (never fabricated). Country in Record.dimension.
"""
import json
import logging
import os
from datetime import date
from typing import Dict, List, Optional

from shared.data.base_client import Record
from shared.data.lineage import Lineage

logger = logging.getLogger("sdq.data.gdelt_bq")

GKG_TABLE = "gdelt-bq.gdeltv2.gkg_partitioned"
WINDOW_DAYS = 30

# GDELT V2Locations carries FIPS 10-4 country codes (not ISO). Map FIPS → our ISO2.
FIPS_TO_ISO2: Dict[str, str] = {
    "DR": "DO", "CS": "CR", "PM": "PA", "GT": "GT", "JM": "JM",
}


class GdeltBQError(RuntimeError):
    """BigQuery is misconfigured (no credentials) or the query failed."""


def build_query() -> str:
    """The partition-pruned events query. Parameterized by @days and @fips."""
    return f"""
    SELECT
      fips,
      AVG(tone) AS news_sentiment,
      100 * SAFE_DIVIDE(COUNTIF(is_protest), COUNT(*)) AS unrest_shocks,
      100 * SAFE_DIVIDE(COUNTIF(is_sanction), COUNT(*)) AS sanctions_signal
    FROM (
      SELECT
        SPLIT(loc, '#')[SAFE_OFFSET(2)] AS fips,
        SAFE_CAST(SPLIT(V2Tone, ',')[SAFE_OFFSET(0)] AS FLOAT64) AS tone,
        (V2Themes LIKE '%PROTEST%') AS is_protest,
        (V2Themes LIKE '%ECON_SANCTIONS%') AS is_sanction
      FROM `{GKG_TABLE}`, UNNEST(SPLIT(V2Locations, ';')) AS loc
      WHERE DATE(_PARTITIONTIME) >= DATE_SUB(CURRENT_DATE(), INTERVAL @days DAY)
        AND V2Tone IS NOT NULL AND V2Tone != ''
    )
    WHERE fips IN UNNEST(@fips)
    GROUP BY fips
    """


# Column → (variable, unit). news_sentiment is a tone (−100..100); the two theme
# shares are 0-100 (higher = worse → risk-increasing in the doctrine).
_VARS = {
    "news_sentiment": "tono GDELT (−100..100)",
    "unrest_shocks": "% de cobertura con tema PROTEST",
    "sanctions_signal": "% de cobertura con tema ECON_SANCTIONS",
}


def rows_to_records(rows: List[dict]) -> List[Record]:
    """Map BigQuery result rows (``{fips, news_sentiment, unrest_shocks,
    sanctions_signal}``) into normalized records, one per (country, variable).

    A row's FIPS not in the peer map is skipped; a None metric stays None (the
    declared rubric remains the fallback). Pure — unit-tested without BigQuery.
    """
    lineage = Lineage(
        source="GDELT_BQ", license="GDELT Project (open data) · BigQuery public dataset",
        fetched_at=date.today(), url=f"bigquery://{GKG_TABLE}",
        note=f"GKG particionado, ventana {WINDOW_DAYS}d",
    )
    out: List[Record] = []
    for row in rows:
        iso2 = FIPS_TO_ISO2.get(row.get("fips"))
        if not iso2:
            continue
        for var, unit in _VARS.items():
            val = row.get(var)
            out.append(Record(
                series=var, period=str(date.today().year),
                value=None if val is None else round(float(val), 3),
                lineage=lineage, unit=unit, dimension=iso2,
            ))
    return out


def fetch_events(days: int = WINDOW_DAYS) -> List[Record]:  # pragma: no cover - needs BigQuery + creds
    """Run the events query against BigQuery and return normalized records.

    Reads service-account credentials from ``GCP_SA_JSON``. Raises
    :class:`GdeltBQError` if unconfigured. The caller (sync) is best-effort.
    """
    raw = os.environ.get("GCP_SA_JSON")
    if not raw:
        raise GdeltBQError("GCP_SA_JSON no configurado (credencial de service account)")
    try:
        from google.cloud import bigquery
        from google.oauth2 import service_account
    except ImportError as e:
        raise GdeltBQError(f"google-cloud-bigquery no instalado: {e}")

    info = json.loads(raw)
    creds = service_account.Credentials.from_service_account_info(info)
    client = bigquery.Client(project=info.get("project_id"), credentials=creds)
    job_config = bigquery.QueryJobConfig(query_parameters=[
        bigquery.ScalarQueryParameter("days", "INT64", days),
        bigquery.ArrayQueryParameter("fips", "STRING", list(FIPS_TO_ISO2.keys())),
    ])
    rows = [dict(r) for r in client.query(build_query(), job_config=job_config).result()]
    logger.info("GDELT-BQ: %d países con datos de eventos", len(rows))
    return rows_to_records(rows)


# ── Historical instability events (for the IRMP backtest, governance outcome) ──
EVENTS_TABLE = "gdelt-bq.gdeltv2.events"
# CAMEO root codes for instability: protest, coerce, assault, fight, mass violence.
INSTABILITY_ROOTS = ("14", "17", "18", "19", "20")


def build_events_query() -> str:
    """Instability-event count per (FIPS country, year) from GDELT Events 2.0.

    Counts high-intensity CAMEO events located in each peer country. Selects only
    Year / EventRootCode / ActionGeo_CountryCode (column pruning) and filters by
    Year + country + root code. Parameterized by @start_year and @fips.
    """
    roots = ",".join(f"'{r}'" for r in INSTABILITY_ROOTS)
    return f"""
    SELECT
      ActionGeo_CountryCode AS fips,
      Year AS year,
      COUNT(*) AS instability_events
    FROM `{EVENTS_TABLE}`
    WHERE Year >= @start_year
      AND EventRootCode IN ({roots})
      AND ActionGeo_CountryCode IN UNNEST(@fips)
    GROUP BY fips, year
    """


def _events_job_config(start_year: int, dry_run: bool = False):  # pragma: no cover - needs BigQuery
    from google.cloud import bigquery
    return bigquery.QueryJobConfig(
        dry_run=dry_run, use_query_cache=not dry_run,
        query_parameters=[
            bigquery.ScalarQueryParameter("start_year", "INT64", start_year),
            bigquery.ArrayQueryParameter("fips", "STRING", list(FIPS_TO_ISO2.keys())),
        ],
    )


def _bq_client():  # pragma: no cover - needs BigQuery + creds
    raw = os.environ.get("GCP_SA_JSON")
    if not raw:
        raise GdeltBQError("GCP_SA_JSON no configurado")
    from google.cloud import bigquery
    from google.oauth2 import service_account
    info = json.loads(raw)
    creds = service_account.Credentials.from_service_account_info(info)
    return bigquery.Client(project=info.get("project_id"), credentials=creds)


def fetch_instability_events(start_year: int = 2014) -> Dict[str, Dict[int, int]]:  # pragma: no cover - needs BigQuery
    """Return ``{iso2: {year: instability_event_count}}`` from GDELT Events."""
    client = _bq_client()
    rows = client.query(build_events_query(), job_config=_events_job_config(start_year)).result()
    out: Dict[str, Dict[int, int]] = {}
    for r in rows:
        iso2 = FIPS_TO_ISO2.get(r["fips"])
        if iso2 and r["year"]:
            out.setdefault(iso2, {})[int(r["year"])] = int(r["instability_events"])
    return out


def events_dry_run_bytes(start_year: int = 2014) -> int:  # pragma: no cover - needs BigQuery + creds
    """Bytes the instability-events query would scan (free dry run, cost check)."""
    client = _bq_client()
    return client.query(build_events_query(),
                        job_config=_events_job_config(start_year, dry_run=True)).total_bytes_processed


def dry_run_bytes(days: int = WINDOW_DAYS) -> int:  # pragma: no cover - needs BigQuery + creds
    """Bytes the events query would scan (a free dry run — for cost validation)."""
    raw = os.environ.get("GCP_SA_JSON")
    if not raw:
        raise GdeltBQError("GCP_SA_JSON no configurado")
    from google.cloud import bigquery
    from google.oauth2 import service_account
    info = json.loads(raw)
    creds = service_account.Credentials.from_service_account_info(info)
    client = bigquery.Client(project=info.get("project_id"), credentials=creds)
    cfg = bigquery.QueryJobConfig(
        dry_run=True, use_query_cache=False,
        query_parameters=[
            bigquery.ScalarQueryParameter("days", "INT64", days),
            bigquery.ArrayQueryParameter("fips", "STRING", list(FIPS_TO_ISO2.keys())),
        ],
    )
    return client.query(build_query(), job_config=cfg).total_bytes_processed
