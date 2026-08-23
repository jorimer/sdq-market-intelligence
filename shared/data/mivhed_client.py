"""MIVHED connector — DR building-permit activity (Eje Construcción).

Public open data from the **Ministerio de la Vivienda, Hábitat y Edificaciones
(MIVHED)**, dataset "Licencias emitidas por MIVHED" on the national open-data portal
(datos.gob.do, CKAN). It is a TRANSACTIONAL file — one row per construction permit — with
issue date, province, municipality, typology, square metres and total investment (RD$).
Permitting is the canonical *leading* indicator of construction activity: it precedes the
actual build, so it anchors the pipeline dimension of the construction index (ICC).

The CSV opens with two banner rows before the real header ("Fecha de Emisión, Mes, Año,
…"); we locate the header row tolerantly. CSV URLs change when MIVHED republishes, so we
resolve the current CSV resource via the CKAN ``package_show`` API, then fetch it. The
file is UTF-8 (BOM) and comma-separated; the issue date is ``MM/DD/YYYY``.

We aggregate to ANNUAL totals (permits, m², investment) plus the per-typology and
per-province permit mix (for the diversification dimensions). The number of distinct
months present per year is kept so the caller can drop a partial current year — never
fabricating a full year from a quarter.
"""
import csv
import io
import logging
import unicodedata
from typing import Any, Dict, Optional

logger = logging.getLogger("sdq.data.mivhed")

_CKAN = "https://datos.gob.do/api/3/action/package_show"
_HEADERS = {"User-Agent": "Mozilla/5.0 (SDQ-MIP)"}

SLUG_LICENSES = "licencias-emitidas"

# Canonical header tokens (normalized) → field role.
_COL_YEAR = ("ano",)            # "Año"
_COL_MONTH = ("mes",)
_COL_TYPOLOGY = ("tipologia",)
_COL_SQM = ("metros cuadrados",)
_COL_INVESTMENT = ("inversion total",)
_COL_PROVINCE = ("provincia",)


def _norm(s: str) -> str:
    t = "".join(c for c in unicodedata.normalize("NFKD", str(s).lower())
                if not unicodedata.combining(c))
    return " ".join(t.replace("(", " ").replace(")", " ").split())


def _num(s: Optional[str]) -> Optional[float]:
    if s is None:
        return None
    t = str(s).strip().replace(",", "")
    if not t:
        return None
    try:
        return float(t)
    except ValueError:
        return None


def _find_header(rows) -> Optional[int]:
    """Index of the row that carries the real column header (the one with a year column
    AND a typology/sqm column) — skips the banner rows."""
    for i, row in enumerate(rows[:10]):
        norms = {_norm(c) for c in row}
        if any(t in norms for t in _COL_YEAR) and (
                any(t in norms for t in _COL_TYPOLOGY)
                or any(t in norms for t in _COL_SQM)):
            return i
    return None


def parse_licenses(text: str) -> Dict[int, Dict[str, Any]]:
    """``{year: {permits, sqm, investment, months, by_typology, by_typology_detail,
    by_province}}`` from the MIVHED permit CSV.

    Aggregates the per-permit rows to annual totals. ``months`` is the count of distinct
    months seen that year (so the caller can drop a partial year). Empty numeric cells are
    treated as 0 for the totals but never fabricated as a year.

    ``by_typology`` is the per-typology PERMIT COUNT (drives the HHI diversification
    dimension). ``by_typology_detail`` desagrega además los m² licenciados y la ``inversion``
    por tipología — ``{typology: {permits, sqm, investment}}`` — porque esos campos ya vienen
    en el dataset crudo por fila; sostiene la lectura de m² licenciados por tipo de
    construcción (p.ej. Comercial y oficinas).

    ⚠️ AVISO sobre ``investment`` (columna "Inversión Total" del MIVHED): NO es un valor
    declarado ni tasado por permiso — es un **costo estándar derivado** = m² × una tarifa fija
    por año (verificado 2026-07-14: el 94 % de las filas es exactamente m² × RD$61,600 y el
    resto m² × RD$57,200). Por tipología es por tanto **redundante con los m²** (comparte la
    misma tarifa) y NO equivale al "valor tasado" de la ONE (≈RD$14,946/m² tasado, ~4× menor).
    Se conserva por fidelidad al dato crudo, pero el producto NO lo expone por tipología como
    métrica monetaria independiente — la señal real por tipología son los m²."""
    rows = list(csv.reader(io.StringIO(text.lstrip("﻿"))))
    hi = _find_header(rows)
    if hi is None:
        return {}
    header = rows[hi]
    idx: Dict[str, int] = {}
    for i, h in enumerate(header):
        n = _norm(h)
        if n in _COL_YEAR:
            idx["year"] = i
        elif n in _COL_MONTH:
            idx["month"] = i
        elif n in _COL_TYPOLOGY:
            idx["typology"] = i
        elif n in _COL_SQM:
            idx["sqm"] = i
        elif n in _COL_INVESTMENT:
            idx["investment"] = i
        elif n in _COL_PROVINCE:
            idx["province"] = i
    if "year" not in idx:
        return {}

    out: Dict[int, Dict[str, Any]] = {}
    for row in rows[hi + 1:]:
        if len(row) <= idx["year"]:
            continue
        ys = row[idx["year"]].strip()
        if not (len(ys) == 4 and ys.isdigit()):
            continue
        year = int(ys)
        rec = out.setdefault(year, {"permits": 0, "sqm": 0.0, "investment": 0.0,
                                    "_months": set(), "by_typology": {},
                                    "by_typology_detail": {}, "by_province": {}})
        rec["permits"] += 1
        sqm = _num(row[idx["sqm"]]) if "sqm" in idx and idx["sqm"] < len(row) else None
        inv = (_num(row[idx["investment"]])
               if "investment" in idx and idx["investment"] < len(row) else None)
        sqm_val, inv_val = sqm or 0.0, inv or 0.0
        rec["sqm"] += sqm_val
        rec["investment"] += inv_val
        if "month" in idx and idx["month"] < len(row):
            m = row[idx["month"]].strip().upper()
            if m:
                rec["_months"].add(m)
        if "typology" in idx and idx["typology"] < len(row):
            t = row[idx["typology"]].strip().upper() or "SIN CLASIFICAR"
            rec["by_typology"][t] = rec["by_typology"].get(t, 0) + 1
            d = rec["by_typology_detail"].setdefault(
                t, {"permits": 0, "sqm": 0.0, "investment": 0.0})
            d["permits"] += 1
            d["sqm"] += sqm_val
            d["investment"] += inv_val
        if "province" in idx and idx["province"] < len(row):
            p = row[idx["province"]].strip().upper() or "SIN PROVINCIA"
            rec["by_province"][p] = rec["by_province"].get(p, 0) + 1

    for rec in out.values():
        rec["months"] = len(rec.pop("_months"))
    return out


class MIVHEDClient:
    source = "MIVHED (Ministerio de la Vivienda, Hábitat y Edificaciones)"
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
        raise RuntimeError(f"MIVHED: sin recurso CSV para '{slug}'")

    def _fetch_csv(self, slug: str) -> str:
        import httpx
        url = self._resolve_csv(slug)
        with httpx.Client(timeout=120, follow_redirects=True, headers=_HEADERS) as http:
            return http.get(url).content.decode("utf-8-sig")

    def licenses(self) -> Dict[int, Dict[str, Any]]:
        return parse_licenses(self._fetch_csv(SLUG_LICENSES))


mivhed_client = MIVHEDClient()
