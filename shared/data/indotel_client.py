"""INDOTEL connector — DR telecom sector indicators.

Public open data from INDOTEL's quarterly statistical-indicators bulletins
(``indotel.gob.do``), machine-readable XLSX. The bulletin's "Ind. Generales"
sheet carries the headline totals by CÓDIGO (line totals LTT, internet
subscriptions TSI, broadband TSIBA), and "RESUMEN" the annual revenue series.

NOTE (data reality, 2026-06): the latest bulletin PUBLISHED on the canonical page
is 2022-Q1; INDOTEL's public quarterly series appears frozen there. The connector
ingests the latest published bulletin honestly — freshness (quarterly cadence) will
reflect its true age, so the product stays cabled-but-not-publishable until a newer
bulletin appears. Never fabricated. Re-point ``LATEST_BULLETIN`` when INDOTEL
publishes a newer file (or wire the INDOTEL–ONE automated portal when it exists).
"""
import logging
from typing import Any, Dict, Optional

logger = logging.getLogger("sdq.data.indotel")

_HEADERS = {"User-Agent": "Mozilla/5.0 (SDQ-MIP)"}

# Latest published quarterly bulletin (XLSX) + the period it covers.
LATEST_BULLETIN = (
    "https://indotel.gob.do/wp-content/uploads/2022/10/"
    "indicadores-estadisticos-de-telecomunicaciones-trimestrales-enero-marzo-2022-res-026-21-web.xlsx"
)
LATEST_PERIOD = "2022-Q1"

# DR population — ONE, X Censo Nacional de Población y Vivienda 2022 (oficial).
# Denominador real de las tasas de penetración (no fabricado).
POP_2022 = 10_760_028


def parse_indicators(xlsx_bytes: bytes) -> Dict[str, Optional[float]]:
    """Extract the headline telecom totals from a bulletin XLSX (bytes).

    Reads "Ind. Generales" (CÓDIGO in col 3, TOTALES in col 5) for the latest month
    of the quarter — line totals (LTT.3er), internet subs (TSI.3er), broadband
    (TSIBA) — and "RESUMEN" for the annual revenue series. Missing → None (never
    fabricated)."""
    import io

    import openpyxl

    wb = openpyxl.load_workbook(io.BytesIO(xlsx_bytes), read_only=True, data_only=True)
    codes: Dict[str, float] = {}
    if "Ind. Generales" in wb.sheetnames:
        for row in wb["Ind. Generales"].iter_rows(values_only=True):
            code = row[2] if len(row) > 2 else None
            total = row[4] if len(row) > 4 else None
            if code and isinstance(total, (int, float)):
                codes[str(code).strip()] = float(total)

    def _pick(*keys: str) -> Optional[float]:
        for k in keys:
            if k in codes:
                return codes[k]
        return None

    lines = _pick("LTT.3er", "LTT.2do", "LTT.1er")
    internet = _pick("TSI.3er", "TSI.2do", "TSI.1er")
    broadband = _pick("TSIBA")

    revenue_latest = revenue_prev = None
    if "RESUMEN" in wb.sheetnames:
        for row in wb["RESUMEN"].iter_rows(values_only=True):
            if row and row[0] and "ngresos Totales" in str(row[0]):
                nums = [c for c in row[1:] if isinstance(c, (int, float))]
                # El RESUMEN lista años completos seguidos del trimestre parcial en curso
                # (p.ej. 2019, 2020, 2021, Ene-Mar.22). Para nivel/crecimiento ANUAL se
                # descarta el parcial final y se toman los DOS últimos años completos
                # (robusto a cuántos años traiga el boletín, no índices fijos).
                complete = nums[:-1] if len(nums) >= 2 else nums
                if len(complete) >= 2:
                    revenue_latest, revenue_prev = complete[-1], complete[-2]
                elif complete:
                    revenue_latest = complete[-1]
                break

    return {
        "lines_total": lines,
        "internet_total": internet,
        "broadband_total": broadband,
        "revenue_latest": revenue_latest,
        "revenue_prev": revenue_prev,
    }


class INDOTELClient:
    source = "INDOTEL"
    license = "Datos Abiertos RD (INDOTEL)"
    license_ok = True

    def fetch_indicators(self) -> Dict[str, Any]:
        """Download the latest published bulletin and parse the headline indicators.

        Returns ``{period, **indicators}``. Raises on network failure (caller treats
        the sync as best-effort)."""
        import httpx

        with httpx.Client(timeout=120, follow_redirects=True, headers=_HEADERS) as http:
            content = http.get(LATEST_BULLETIN).content
        return {"period": LATEST_PERIOD, **parse_indicators(content)}


indotel_client = INDOTELClient()
