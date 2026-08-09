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
# Fuente única (24 países) en shared.data.latam_peers.
from shared.data.latam_peers import fips_to_iso2

FIPS_TO_ISO2: Dict[str, str] = fips_to_iso2()


class GdeltBQError(RuntimeError):
    """BigQuery is misconfigured (no credentials) or the query failed."""


def build_query() -> str:
    """The partition-pruned events query. Parameterized by @days and @fips."""
    return _query_body(
        "DATE(_PARTITIONTIME) >= DATE_SUB(CURRENT_DATE(), INTERVAL @days DAY)")


def build_query_for_year() -> str:
    """Historical variant: events for a full calendar @year (para el backfill de
    trayectoria). El GKG particionado del dataset público cubre desde ~2015."""
    return _query_body(
        "DATE(_PARTITIONTIME) BETWEEN DATE(@year, 1, 1) AND DATE(@year, 12, 31)")


def _query_body(partition_filter: str) -> str:
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
      WHERE {partition_filter}
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


def rows_to_records(rows: List[dict], period: Optional[str] = None,
                    note: Optional[str] = None) -> List[Record]:
    """Map BigQuery result rows (``{fips, news_sentiment, unrest_shocks,
    sanctions_signal}``) into normalized records, one per (country, variable).

    *period* defaults to the current year (ventana reciente); el backfill histórico
    pasa el año consultado. A row's FIPS not in the peer map is skipped; a None metric
    stays None (the declared rubric remains the fallback). Pure — sin BigQuery.
    """
    period = period or str(date.today().year)
    lineage = Lineage(
        source="GDELT_BQ", license="GDELT Project (open data) · BigQuery public dataset",
        fetched_at=date.today(), url=f"bigquery://{GKG_TABLE}",
        note=note or f"GKG particionado, ventana {WINDOW_DAYS}d",
    )
    out: List[Record] = []
    for row in rows:
        iso2 = FIPS_TO_ISO2.get(row.get("fips"))
        if not iso2:
            continue
        for var, unit in _VARS.items():
            val = row.get(var)
            out.append(Record(
                series=var, period=period,
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


def fetch_events_for_year(year: int) -> List[Record]:  # pragma: no cover - needs BigQuery + creds
    """Eventos GDELT de un año calendario completo (para el backfill de trayectoria).
    Mismo esquema que :func:`fetch_events` pero particionado por *year* en vez de la
    ventana reciente. Registros estampados al período ``year``."""
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
        bigquery.ScalarQueryParameter("year", "INT64", year),
        bigquery.ArrayQueryParameter("fips", "STRING", list(FIPS_TO_ISO2.keys())),
    ])
    rows = [dict(r) for r in client.query(build_query_for_year(), job_config=job_config).result()]
    logger.info("GDELT-BQ %d: %d países con eventos", year, len(rows))
    return rows_to_records(rows, period=str(year), note=f"GKG particionado, año {year}")


# ── Eventos SUB-NACIONALES (ADM1 = provincia) ─────────────────────────────
# El país sale del offset 2 de V2Locations; el offset 3 es el código ADM1 — la
# provincia. La granularidad SIEMPRE estuvo en la misma tabla: la consulta la
# descartaba. Esto habilita una señal de eventos por demarcación, que es lo único del
# IRMP que puede variar dentro del país (macro, externo, político y regulatorio se
# miden a nivel país por construcción: WGI, rating soberano, cuentas nacionales).
#
# El código ADM1 NO se traduce con una tabla FIPS escrita a mano: la consulta devuelve
# también el nombre de lugar dominante de cada ADM1 y el mapeo se DERIVA de ese nombre
# contra el padrón provincial. Un código nuevo o renombrado aparece como no resuelto —
# visible— en vez de caer en la provincia equivocada.
DO_FIPS = "DR"

# Volumen mínimo de registros para que el tono y las cuotas temáticas de una provincia
# signifiquen algo. Es un SUPUESTO declarado, no una medición: el geocodificado de GDELT
# se concentra en Santo Domingo y Santiago, así que las provincias chicas devuelven
# muestras diminutas donde una sola nota mueve el promedio. Por debajo del umbral la
# observación viaja con ``value=None`` y su razón — nulo honesto, no un cero que el
# consumidor leería como "sin tensión".
MIN_ADM1_RECORDS = 200
_THIN_REASON = "muestra insuficiente en GDELT para esta provincia"
_UNMAPPED_REASON = "código ADM1 sin provincia reconocida"


def build_adm1_query() -> str:
    """Eventos agregados por ADM1 dentro de un país. Parametrizada por @days y @fips.

    Devuelve, además de las tres métricas, ``n_records`` (para la regla de volumen) y
    ``top_name`` (el nombre de lugar dominante, que resuelve el código ADM1 a provincia
    sin una tabla FIPS de memoria)."""
    return f"""
    SELECT
      adm1,
      COUNT(*) AS n_records,
      APPROX_TOP_COUNT(place_name, 1)[OFFSET(0)].value AS top_name,
      AVG(tone) AS news_sentiment,
      100 * SAFE_DIVIDE(COUNTIF(is_protest), COUNT(*)) AS unrest_shocks,
      100 * SAFE_DIVIDE(COUNTIF(is_sanction), COUNT(*)) AS sanctions_signal
    FROM (
      SELECT
        SPLIT(loc, '#')[SAFE_OFFSET(2)] AS fips,
        SPLIT(loc, '#')[SAFE_OFFSET(3)] AS adm1,
        SPLIT(loc, '#')[SAFE_OFFSET(1)] AS place_name,
        SAFE_CAST(SPLIT(V2Tone, ',')[SAFE_OFFSET(0)] AS FLOAT64) AS tone,
        (V2Themes LIKE '%PROTEST%') AS is_protest,
        (V2Themes LIKE '%ECON_SANCTIONS%') AS is_sanction
      FROM `{GKG_TABLE}`, UNNEST(SPLIT(V2Locations, ';')) AS loc
      WHERE DATE(_PARTITIONTIME) >= DATE_SUB(CURRENT_DATE(), INTERVAL @days DAY)
        AND V2Tone IS NOT NULL AND V2Tone != ''
    )
    WHERE fips = @fips AND adm1 IS NOT NULL AND adm1 != ''
    GROUP BY adm1
    """


def adm1_rows_to_records(rows: List[dict], period: Optional[str] = None,
                         min_records: int = MIN_ADM1_RECORDS) -> List[Record]:
    """Filas ADM1 de BigQuery → registros por PROVINCIA, con la regla de volumen.

    Tres resultados posibles por fila, todos explícitos:

    * el ADM1 no resuelve a una provincia del padrón → se descarta y se registra;
    * resuelve pero no llega al volumen mínimo → tres registros con ``value=None`` y
      su razón (el consumidor sabe que la provincia existe y que no la medimos);
    * resuelve y hay volumen → los tres valores.

    Pura (sin BigQuery), para poder fijar la regla en tests."""
    from shared.reference.provinces import province_slug

    period = period or str(date.today().year)
    lineage = Lineage(
        source="GDELT_BQ", license="GDELT Project (open data) · BigQuery public dataset",
        fetched_at=date.today(), url=f"bigquery://{GKG_TABLE}",
        note=f"GKG particionado por ADM1, ventana {WINDOW_DAYS}d",
    )
    out: List[Record] = []
    unresolved: List[str] = []
    for row in rows:
        slug = province_slug(row.get("top_name"))
        if slug is None:
            unresolved.append(f"{row.get('adm1')} ({row.get('top_name')})")
            continue
        n = int(row.get("n_records") or 0)
        thin = n < min_records
        for var, unit in _VARS.items():
            val = row.get(var)
            out.append(Record(
                series=var, period=period,
                value=None if (thin or val is None) else round(float(val), 3),
                lineage=lineage, unit=unit, dimension=slug,
                reason=(_THIN_REASON if thin else None),
            ))
    if unresolved:
        logger.warning("[GDELT] ADM1 sin provincia reconocida (descartados): %s",
                       sorted(unresolved))
    return out


def adm1_volume_report(rows: List[dict],
                       min_records: int = MIN_ADM1_RECORDS) -> Dict[str, object]:
    """Resumen de la PRUEBA DE VOLUMEN: cuántas provincias quedan medibles.

    Es el gate que decide si esta señal se publica. Una dimensión de eventos que solo
    distingue a Santo Domingo y Santiago no aporta granularidad: reparte dos valores y
    treinta nulos, y eso hay que verlo ANTES de cablearla, no después."""
    from shared.reference.provinces import PROVINCES, province_slug

    measurable: Dict[str, int] = {}
    thin: Dict[str, int] = {}
    unresolved: List[str] = []
    for row in rows:
        slug = province_slug(row.get("top_name"))
        if slug is None:
            unresolved.append(str(row.get("adm1")))
            continue
        n = int(row.get("n_records") or 0)
        (measurable if n >= min_records else thin)[slug] = n
    covered = set(measurable) | set(thin)
    absent = sorted({s for s, _n, _r in PROVINCES} - covered)
    return {
        "min_records": min_records,
        "n_provinces_measurable": len(measurable),
        "n_provinces_thin": len(thin),
        "n_provinces_absent": len(absent),
        "measurable": dict(sorted(measurable.items(), key=lambda kv: -kv[1])),
        "thin": dict(sorted(thin.items(), key=lambda kv: -kv[1])),
        "absent": absent,
        "unresolved_adm1": sorted(unresolved),
        # El veredicto es del dueño, no del código: acá solo va la cifra que lo informa.
        "share_measurable": round(len(measurable) / 32, 3),
    }


def fetch_events_by_adm1(days: int = WINDOW_DAYS,
                         fips: str = DO_FIPS) -> List[Record]:  # pragma: no cover - needs BigQuery + creds
    """Eventos GDELT por provincia. Mismo esquema que :func:`fetch_events`, con la
    regla de volumen aplicada (nulo honesto por debajo del umbral)."""
    client = _bq_client()
    from google.cloud import bigquery

    job_config = bigquery.QueryJobConfig(query_parameters=[
        bigquery.ScalarQueryParameter("days", "INT64", days),
        bigquery.ScalarQueryParameter("fips", "STRING", fips),
    ])
    rows = [dict(r) for r in client.query(build_adm1_query(), job_config=job_config).result()]
    logger.info("GDELT-BQ ADM1: %d demarcaciones con datos", len(rows))
    return adm1_rows_to_records(rows)


def adm1_volume_test(days: int = WINDOW_DAYS,
                     fips: str = DO_FIPS) -> Dict[str, object]:  # pragma: no cover - needs BigQuery + creds
    """Corre la consulta ADM1 y devuelve el informe de volumen (sin persistir nada).

    Este es el paso que debe correrse ANTES de publicar la señal provincial."""
    client = _bq_client()
    from google.cloud import bigquery

    job_config = bigquery.QueryJobConfig(query_parameters=[
        bigquery.ScalarQueryParameter("days", "INT64", days),
        bigquery.ScalarQueryParameter("fips", "STRING", fips),
    ])
    rows = [dict(r) for r in client.query(build_adm1_query(), job_config=job_config).result()]
    return adm1_volume_report(rows)


def adm1_dry_run_bytes(days: int = WINDOW_DAYS,
                       fips: str = DO_FIPS) -> int:  # pragma: no cover - needs BigQuery + creds
    """Bytes que escanearía la consulta ADM1 (dry run gratuito — control de costo).

    La consulta lee las MISMAS columnas y la misma partición que la de país: agrupar por
    ADM1 no cambia lo escaneado, así que debe caer dentro del mismo presupuesto del tier
    gratuito. Verificarlo es barato; suponerlo, no."""
    client = _bq_client()
    from google.cloud import bigquery

    cfg = bigquery.QueryJobConfig(
        dry_run=True, use_query_cache=False,
        query_parameters=[
            bigquery.ScalarQueryParameter("days", "INT64", days),
            bigquery.ScalarQueryParameter("fips", "STRING", fips),
        ],
    )
    return client.query(build_adm1_query(), job_config=cfg).total_bytes_processed


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


def _events_job_config(start_year: int, fips: Optional[List[str]] = None, dry_run: bool = False):  # pragma: no cover - needs BigQuery
    from google.cloud import bigquery
    return bigquery.QueryJobConfig(
        dry_run=dry_run, use_query_cache=not dry_run,
        query_parameters=[
            bigquery.ScalarQueryParameter("start_year", "INT64", start_year),
            bigquery.ArrayQueryParameter("fips", "STRING", fips or list(FIPS_TO_ISO2.keys())),
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


def fetch_instability_events(start_year: int = 2014,
                             fips_map: Optional[Dict[str, str]] = None) -> Dict[str, Dict[int, int]]:  # pragma: no cover - needs BigQuery
    """Return ``{iso2: {year: instability_event_count}}`` from GDELT Events.

    *fips_map* (FIPS → iso2) selects the countries; defaults to the production peer
    set. A FIPS not present in the data simply yields no rows for that country.
    """
    fmap = fips_map or FIPS_TO_ISO2
    client = _bq_client()
    rows = client.query(build_events_query(),
                        job_config=_events_job_config(start_year, list(fmap.keys()))).result()
    out: Dict[str, Dict[int, int]] = {}
    for r in rows:
        iso2 = fmap.get(r["fips"])
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
