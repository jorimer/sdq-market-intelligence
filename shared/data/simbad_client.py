"""SIMBAD (public Apache Superset of the Superintendencia de Bancos) — fallback source.

The SB publishes the full supervised universe (FINANCIERO + CAMBIARIO), **monthly**, via
a PUBLIC Superset whose chart-data API needs no auth (POST /api/v1/chart/data with a
query_context). We use it as a **fallback** for the open statistics API
(``apis.sb.gob.do``) when a period/entity isn't published there — notably the AC
cambiarias, whose 2026 figures are in SIMBAD but not (yet) in the open API — and as a QA
oracle.

Reading rules (see the ``simbad-public-oracle`` memory):
- Read the **TODOS-cascade subtotal** of each node, never sum the children (double-counts).
- Balance is a stock → take the **closing-month** snapshot. Results are **YTD** (reset each
  January) → take the closing-month value. Both reuse ``SIBDataClient._map_eic_to_sdq_fields``
  so the SIMBAD path and the API path produce identical figures.

Datasets (dashboard 24 "Entidades Cambiarias"):
- 35 = balance/situación: cols ``Año, Mes, TIPO_DE_ENTIDAD, ENTIDAD, CONCEPTO_NIVEL_1/2/3, MONTO``
- 34 = resultados: cols ``FECHA`` (epoch-ms), ``CONCEPTO_NIVEL_1..7, MONTO``
"""
from __future__ import annotations

import json
import logging
import urllib.error
import urllib.request
from datetime import date, datetime, timezone
from typing import Dict, List, Optional, Tuple

from shared.data.sib_data_client import (
    SIBDataClient,
    cambiaria_display_name,
)

logger = logging.getLogger("sdq.banking_score.simbad")

SIMBAD_BASE = "https://simbad.sb.gob.do"
DATASET_BALANCE = 35
DATASET_INCOME = 34
_QUARTER_MONTHS = (3, 6, 9, 12)
_CAMBIARIA_SYSTEM = "CAMBIARIO"


def _post_chart_data(dataset_id: int, columns: List[str], filters: List[Dict],
                     row_limit: int = 200000, timeout: int = 90) -> List[Dict]:
    """Run an arbitrary Superset query against a public dataset (no auth)."""
    qc = {
        "datasource": {"id": dataset_id, "type": "table"},
        "queries": [{"columns": columns, "filters": filters, "row_limit": row_limit}],
        "result_format": "json",
        "result_type": "results",
    }
    req = urllib.request.Request(
        f"{SIMBAD_BASE}/api/v1/chart/data",
        data=json.dumps(qc).encode(),
        method="POST",
        headers={"Content-Type": "application/json", "Accept": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        payload = json.loads(resp.read())
    data = payload["result"][0].get("data", []) or []
    if len(data) >= row_limit:
        logger.warning("SIMBAD dataset %s hit row_limit=%d — result may be TRUNCATED; "
                       "narrow the filters or paginate.", dataset_id, row_limit)
    return data


def _to_concept_rows(rows: List[Dict]) -> List[Dict]:
    """SIMBAD column names → the ``conceptoNivelN``/``valor`` shape the EIC mapper reads."""
    out = []
    for r in rows:
        rec: Dict = {"valor": r.get("MONTO")}
        for i in range(1, 8):
            v = r.get(f"CONCEPTO_NIVEL_{i}")
            if v is not None:
                rec[f"conceptoNivel{i}"] = v
        out.append(rec)
    return out


def _fecha_to_year_month(fecha) -> Optional[Tuple[int, int]]:
    """SIMBAD resultados ``FECHA`` is an epoch-ms timestamp at the month-end."""
    if not isinstance(fecha, (int, float)):
        return None
    dt = datetime.fromtimestamp(fecha / 1000, tz=timezone.utc)
    return dt.year, dt.month


def _quarter_years(period_start: str, period_end: str) -> Tuple[int, int]:
    def _yr(s: str, default: int) -> int:
        try:
            return int(str(s).split("-")[0])
        except (ValueError, IndexError, AttributeError):
            return default
    start = _yr(period_start, 2021)
    end = _yr(period_end, datetime.now(tz=timezone.utc).year) if period_end else datetime.now(tz=timezone.utc).year
    return start, end


def extract_cambiaria_bulk(period_start: str = "2021-01", period_end: str = "") -> Dict[str, List[Dict]]:
    """Extract cambiaria (EIC) balance + income from SIMBAD for the **quarter-end months**
    in the range, mapped to BankingData fields.

    Returns the same shape as ``SIBDataClient._extract_eic_bulk``:
    ``{entity: [period dict, …], "_entity_meta": {entity: {...}}}`` so it can be merged
    with / fall back behind the open-API result. Only quarter-end months (3/6/9/12) are
    emitted (the platform is quarterly); each period carries a single month's snapshot.
    """
    start_year, end_year = _quarter_years(period_start, period_end)

    # Query YEAR BY YEAR so neither dataset's row_limit truncates over deep history.
    # Income (dataset 34) is a 7-level tree (~200+ rows per entity-month) and exceeds
    # 200k across the full range; balance (3 levels) is smaller but chunked too for safety.
    # Income has only FECHA (a temporal column; rejects epoch-int filters → ISO strings).
    bal_rows: List[Dict] = []
    inc_rows: List[Dict] = []
    for yr in range(start_year, end_year + 1):
        bal_rows += _post_chart_data(
            DATASET_BALANCE,
            ["Año", "Mes", "ENTIDAD", "CONCEPTO_NIVEL_1", "CONCEPTO_NIVEL_2", "CONCEPTO_NIVEL_3", "MONTO"],
            [
                {"col": "SISTEMA", "op": "==", "val": _CAMBIARIA_SYSTEM},
                {"col": "Año", "op": "==", "val": yr},
                {"col": "Mes", "op": "IN", "val": list(_QUARTER_MONTHS)},
            ],
        )
        inc_rows += _post_chart_data(
            DATASET_INCOME,
            ["FECHA", "ENTIDAD"] + [f"CONCEPTO_NIVEL_{i}" for i in range(1, 8)] + ["MONTO"],
            [
                {"col": "SISTEMA", "op": "==", "val": _CAMBIARIA_SYSTEM},
                {"col": "FECHA", "op": ">=", "val": f"{yr}-01-01"},
                {"col": "FECHA", "op": "<=", "val": f"{yr}-12-31"},
            ],
        )
    logger.info("  SIMBAD cambiaria: %d balance, %d income rows", len(bal_rows), len(inc_rows))

    # Bucket balance by (entidad, quarter-end date); income by the same, parsing FECHA.
    by_ent: Dict[str, Dict[date, Dict[str, List[Dict]]]] = {}

    def _bucket(entidad: str, pe: date, src: str, row: Dict):
        ent = (entidad or "").strip()
        if not ent or ent == "TODOS":
            return
        by_ent.setdefault(ent, {}).setdefault(pe, {"balance": [], "income": []})[src].append(row)

    for r in bal_rows:
        y, m = r.get("Año"), r.get("Mes")
        if not (isinstance(y, int) and m in _QUARTER_MONTHS):
            continue
        _bucket(r.get("ENTIDAD"), SIBDataClient._month_end(f"{y}-{m:02d}"), "balance", r)
    for r in inc_rows:
        ym = _fecha_to_year_month(r.get("FECHA"))
        if not ym or ym[0] < start_year or ym[0] > end_year or ym[1] not in _QUARTER_MONTHS:
            continue
        _bucket(r.get("ENTIDAD"), SIBDataClient._month_end(f"{ym[0]}-{ym[1]:02d}"), "income", r)

    results: Dict[str, List[Dict]] = {}
    meta: Dict[str, Dict] = {}
    for ent, periods in by_ent.items():
        out = []
        for pe, data in periods.items():
            period_data = {
                "balance": _to_concept_rows(data["balance"]),
                "income": _to_concept_rows(data["income"]),
            }
            mapped = SIBDataClient._map_eic_to_sdq_fields(period_data)
            if not mapped.get("activos_totales"):
                continue  # skip empty/near-empty periods (the model reweights on N/D)
            mapped["period_end"] = pe
            mapped["period_type"] = "quarterly"
            mapped["source"] = "sib_simbad"
            out.append(mapped)
        if out:
            results[ent] = out
            meta[ent] = {"sib_code": ent, "tipo_entidad": "AC", "nombre": cambiaria_display_name(ent)}

    results["_entity_meta"] = meta
    logger.info("  SIMBAD cambiaria extract complete: %d entities", len(meta))
    return results
