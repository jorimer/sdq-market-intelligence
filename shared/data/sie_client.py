"""SIE (Superintendencia de Electricidad) connector — DR power-sector statistics.

Public open data from the SIE, published on the national open-data portal
(datos.gob.do, CKAN) and served as CSV from sie.gob.do. Two datasets feed the
energy resilience index (Eje Energía):

  * **Installed capacity** (1998–present): cumulative SENI generation capacity (MW)
    per year → capacity adequacy & expansion pace.
  * **Claims** (monthly, 2019–present): user claims received / decided / in-process
    → a service-quality (consumer reliability) proxy.

DELIBERATELY EXCLUDED — the SIE *fuel consumption* CSV: it has a structural unit
break at 2018 (fuel-oil columns jump ~30×) and the gas column's magnitude is
inconsistent with "MMBTU" as labelled, so a carbon-intensity / transition metric
built on it would be false precision. The transition signal (renewable generation
share by technology) is now ingested separately from the ONE generation-mix dataset
— see ``shared/data/generation_client`` — so it is real data, no longer a gap.

CSV URLs change when SIE republishes (the path carries a date), so we resolve the
current CSV resource per dataset via the CKAN ``package_show`` API, then fetch it.
Files are Latin-1 encoded.
"""
import csv
import io
import logging
from typing import Dict, List, Optional

logger = logging.getLogger("sdq.data.sie")

_CKAN = "https://datos.gob.do/api/3/action/package_show"
_HEADERS = {"User-Agent": "Mozilla/5.0 (SDQ-MIP)"}

# CKAN dataset slugs (stable) → resolved to a dated CSV URL at fetch time.
SLUG_CAPACITY = "historico-potencia-instalada-1998-2024"
SLUG_CLAIMS = "reporte-protecom-julio-2023"

_MONTHS_FULL = {"enero": 1, "febrero": 2, "marzo": 3, "abril": 4, "mayo": 5,
                "junio": 6, "julio": 7, "agosto": 8, "septiembre": 9,
                "octubre": 10, "noviembre": 11, "diciembre": 12}


def _num(s: Optional[str]) -> Optional[float]:
    """Parse a SIE number ('1,947.76', ' 2,841 ') → float, or None if empty/invalid."""
    if s is None:
        return None
    t = s.strip().replace(",", "")
    if not t:
        return None
    try:
        return float(t)
    except ValueError:
        return None


def parse_installed_capacity(text: str) -> Dict[int, float]:
    """``{year: cumulative_capacity_MW}`` from the capacity-movement CSV.

    Layout: two banner rows, then a header whose columns are
    ENTRADA(MW), SALIDA(MW), description, AÑO, POTENCIA(MW). We read the year
    (col 3) and the cumulative installed capacity (col 4); rows without a 4-digit
    year are skipped (banners, blanks)."""
    out: Dict[int, float] = {}
    for row in csv.reader(io.StringIO(text)):
        if len(row) < 5:
            continue
        year_s = row[3].strip()
        if not (len(year_s) == 4 and year_s.isdigit()):
            continue
        mw = _num(row[4])
        if mw is not None:
            out[int(year_s)] = mw
    return out


def parse_claims(text: str) -> List[Dict[str, object]]:
    """``[{period 'YYYY-MM', recibidas, procedentes, improcedentes, total_decisiones,
    en_proceso}]``. Header: Año, Mes, Recibidas, Procedentes, Improcedentes,
    Total Decisiones, En Proceso."""
    out: List[Dict[str, object]] = []
    rows = list(csv.reader(io.StringIO(text)))
    for row in rows[1:]:
        if len(row) < 7:
            continue
        yr = row[0].strip()
        m = _MONTHS_FULL.get(row[1].strip().lower())
        if not (yr.isdigit() and m):
            continue
        out.append({
            "period": f"{int(yr)}-{m:02d}",
            "recibidas": _num(row[2]), "procedentes": _num(row[3]),
            "improcedentes": _num(row[4]), "total_decisiones": _num(row[5]),
            "en_proceso": _num(row[6]),
        })
    out.sort(key=lambda r: r["period"])
    return out


class SIEClient:
    source = "SIE"
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
        """Current CSV resource URL for a CKAN dataset slug (robust to republish)."""
        import httpx
        with httpx.Client(timeout=60, follow_redirects=True, headers=_HEADERS) as http:
            data = http.get(_CKAN, params={"id": slug}).json()
        for r in (data.get("result") or {}).get("resources", []):
            if (r.get("format") or "").upper() == "CSV" and r.get("url"):
                return r["url"]
        raise RuntimeError(f"SIE: sin recurso CSV para '{slug}'")

    def _fetch_csv(self, slug: str) -> str:
        """Download a SIE CSV (Latin-1) via its CKAN-resolved URL."""
        import httpx
        url = self._resolve_csv(slug)
        with httpx.Client(timeout=120, follow_redirects=True, headers=_HEADERS) as http:
            return http.get(url).content.decode("latin-1")

    def installed_capacity(self) -> Dict[int, float]:
        return parse_installed_capacity(self._fetch_csv(SLUG_CAPACITY))

    def claims(self) -> List[Dict[str, object]]:
        return parse_claims(self._fetch_csv(SLUG_CLAIMS))


sie_client = SIEClient()
