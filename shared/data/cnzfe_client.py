"""CNZFE connector — DR free-zone sector fundamentals (Eje Zonas Francas).

Public open data from the **Consejo Nacional de Zonas Francas de Exportación (CNZFE)**,
dataset "Evolución de las principales variables del Sector de Zonas Francas" on the
national open-data portal (datos.gob.do, CKAN). It is a clean yearly series (2006–) of
the sector's fundamentals — approved parks, operating companies, jobs, exports (US$),
accumulated investment (US$), local operating spend, weekly wages, occupied floor area —
the authoritative base for a free-zone attractiveness/health index.

CSV URLs change when CNZFE republishes, so we resolve the current CSV resource via the
CKAN ``package_show`` API, then fetch it. The file is UTF-8 (BOM) and comma-separated.
"""
import csv
import io
import logging
from typing import Dict, Optional

logger = logging.getLogger("sdq.data.cnzfe")

_CKAN = "https://datos.gob.do/api/3/action/package_show"
_HEADERS = {"User-Agent": "Mozilla/5.0 (SDQ-MIP)"}

SLUG_VARS = "principales-variables-del-sector-de-zonas-francas-de-la-republica-dominicana-2006-2025"

# CSV header → canonical field. Matched accent/spacing-insensitively (see ``_norm``).
_FIELDS = {
    "total parques aprobados": "parks",
    "total empresas operando": "companies",
    "total de empleos": "jobs",
    "exportaciones millones us$": "exports_musd",
    "inversion total acumulada millones us$": "investment_musd",
    "gastos operativos locales millones us$": "local_spend_musd",
    "salarios operarios semanales rd$": "wage_operator_rd",
    "salarios tecnicos semanales rd$": "wage_technician_rd",
    "areas de naves ocupadas pies cuadrados": "occupied_area_sqft",
}


def _norm(s: str) -> str:
    import unicodedata
    t = "".join(c for c in unicodedata.normalize("NFKD", s.lower())
                if not unicodedata.combining(c))
    return " ".join(t.replace("(", " ").replace(")", " ").split())


def _num(s: Optional[str]) -> Optional[float]:
    if s is None:
        return None
    t = s.strip().replace(",", "")
    if not t:
        return None
    try:
        return float(t)
    except ValueError:
        return None


def parse_free_zone_vars(text: str) -> Dict[int, Dict[str, float]]:
    """``{year: {field: value}}`` from the CNZFE evolution CSV.

    Maps the header columns to canonical fields; rows without a 4-digit year are
    skipped. Empty cells stay absent (never fabricated)."""
    reader = csv.reader(io.StringIO(text.lstrip("﻿")))  # tolera BOM
    header = next(reader, None)
    if not header:
        return {}
    # column index → canonical field (the year column is matched separately)
    cols: Dict[int, str] = {}
    year_col = None
    for i, h in enumerate(header):
        n = _norm(h)
        if n in ("ano", "año", "anio"):
            year_col = i
        elif n in _FIELDS:
            cols[i] = _FIELDS[n]
    if year_col is None:
        return {}
    out: Dict[int, Dict[str, float]] = {}
    for row in reader:
        if len(row) <= year_col:
            continue
        ys = row[year_col].strip()
        if not (len(ys) == 4 and ys.isdigit()):
            continue
        rec: Dict[str, float] = {}
        for i, field in cols.items():
            if i < len(row):
                v = _num(row[i])
                if v is not None:
                    rec[field] = v
        if rec:
            out[int(ys)] = rec
    return out


class CNZFEClient:
    source = "CNZFE (Consejo Nacional de Zonas Francas)"
    # Verificado el 2026-08-23 contra el propio CKAN del portal
    # (`package_show` → `license_id: odc-odbl`) para el dataset que este conector consume,
    # no para el portal en general: el portal declara licencia POR DATASET y dar por buena
    # una sola cadena para todos era una suposición. Decía «Datos Abiertos RD
    # (datos.gob.do)», que no nombra ninguna cláusula — y ODbL tiene dos.
    license = ("datos.gob.do — Open Database License (ODbL) v1.0, declarada POR DATASET en el "
        "portal: exige el aviso de atribución, y el share-alike alcanza a las bases "
        "DERIVADAS. Un informe o un gráfico es «Produced Work» y NO lo dispara "
        "(§4.5) — https://opendatacommons.org/licenses/odbl/1-0/")
    license_ok = True

    def _resolve_csv(self, slug: str) -> str:
        import httpx
        with httpx.Client(timeout=60, follow_redirects=True, headers=_HEADERS) as http:
            data = http.get(_CKAN, params={"id": slug}).json()
        for r in (data.get("result") or {}).get("resources", []):
            if (r.get("format") or "").upper() == "CSV" and r.get("url"):
                return r["url"]
        raise RuntimeError(f"CNZFE: sin recurso CSV para '{slug}'")

    def _fetch_csv(self, slug: str) -> str:
        import httpx
        url = self._resolve_csv(slug)
        with httpx.Client(timeout=120, follow_redirects=True, headers=_HEADERS) as http:
            return http.get(url).content.decode("utf-8-sig")

    def free_zone_vars(self) -> Dict[int, Dict[str, float]]:
        return parse_free_zone_vars(self._fetch_csv(SLUG_VARS))


cnzfe_client = CNZFEClient()
