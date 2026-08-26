"""Generation-mix connector — DR electricity generation by technology (Eje Energía).

Public open data from the **Oficina Nacional de Estadística (ONE)**, dataset
"Generación de Energía en República Dominicana" on the national open-data portal
(datos.gob.do, CKAN). It reports yearly generation **by technology** (combined
cycle, wind, gas/steam turbines, diesel engines, hydro, solar) in GWh plus a
share column — the authoritative signal for the **energy-transition** dimension
of the IRSE (renewable penetration / decarbonisation of the mix).

This CLOSES a previously declared gap: the SIE connector noted that the transition
signal "lived in OC-SENI PDFs". It is in fact published here as structured CSV, so
we ingest it as real data — no PDF, never fabricated.

Honesty guards on the raw file (verified 2026-06):
  * The number formatting is Latin-1 and ``;``-separated, columns
    ``Tipo de Generación de Energia; Total de Energia; Porcentaje; Año``.
  * The GWh column is corrupted in at least one year (2025: a Solar entry of
    ~23,638 GWh inflates the total to ~47k GWh, while its own share column reads
    9 %). The **percentage column is internally consistent every year** (techs sum
    to ~100), so renewable penetration is computed from the *share* column and any
    year whose shares do not sum to ~100 is dropped. We never trust the GWh value
    where the two disagree.

CSV URLs change when ONE republishes (the path carries a date), so we resolve the
current CSV resource via the CKAN ``package_show`` API, then fetch it.
"""
import csv
import io
import logging
import unicodedata
from typing import Dict, List, Optional

logger = logging.getLogger("sdq.data.generation")

_CKAN = "https://datos.gob.do/api/3/action/package_show"
_HEADERS = {"User-Agent": "Mozilla/5.0 (SDQ-MIP)"}

# Stable CKAN dataset slug → resolved to a dated CSV URL at fetch time.
SLUG_GENERATION = "generacion-de-energi-a-en-republica-dominicana"

# Renewable technologies (matched accent/encoding-insensitively against the row
# label): wind, hydro, solar. The rest (combined cycle, gas/steam turbines, diesel
# engines) are fossil. Biomass is not a column in this dataset today.
_RENEWABLE_KEYS = ("eolica", "hidraulica", "solar")

# A year's technology shares must sum within this tolerance of 100 to be trusted.
_SHARE_SUM_MIN = 95.0
_SHARE_SUM_MAX = 105.0


def _norm(s: str) -> str:
    """Lowercase, strip accents — robust label matching across encodings."""
    return "".join(c for c in unicodedata.normalize("NFKD", s.lower())
                   if not unicodedata.combining(c))


def _num(s: Optional[str]) -> Optional[float]:
    """Parse a number ('1,947.76', ' 26 ') → float, or None if empty/invalid."""
    if s is None:
        return None
    t = s.strip().replace(",", "")
    if not t:
        return None
    try:
        return float(t)
    except ValueError:
        return None


def _is_renewable(label: str) -> bool:
    n = _norm(label)
    return any(k in n for k in _RENEWABLE_KEYS)


def parse_generation_shares(text: str) -> Dict[int, Dict[str, float]]:
    """``{year: {normalised_tech_label: share_pct}}`` from the generation CSV.

    Reads the *Porcentaje* column (robust to the GWh-column corruption). Years are
    kept only when their technology shares sum to ~100; everything else (banners,
    blanks, all-zero pre-history, corrupted years) is dropped."""
    by_year: Dict[int, Dict[str, float]] = {}
    for row in csv.reader(io.StringIO(text), delimiter=";"):
        if len(row) < 4:
            continue
        label = row[0].strip()
        year_s = row[3].strip()
        if not (len(year_s) == 4 and year_s.isdigit()):
            continue
        pct = _num(row[2])
        if not label or pct is None:
            continue
        by_year.setdefault(int(year_s), {})[label] = pct

    clean: Dict[int, Dict[str, float]] = {}
    for year, techs in by_year.items():
        total = sum(techs.values())
        if _SHARE_SUM_MIN <= total <= _SHARE_SUM_MAX:
            clean[year] = techs
        else:
            logger.info("generación %s descartado: las cuotas suman %.1f%% (≠100)",
                        year, total)
    return clean


def renewable_share_by_year(shares_by_year: Dict[int, Dict[str, float]]) -> Dict[int, float]:
    """``{year: renewable_penetration_pct}`` — wind+hydro+solar over the mix."""
    out: Dict[int, float] = {}
    for year, techs in shares_by_year.items():
        ren = sum(v for k, v in techs.items() if _is_renewable(k))
        out[year] = round(ren, 2)
    return out


class GenerationMixClient:
    source = "ONE (Generación de Energía RD)"
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
        raise RuntimeError(f"generación: sin recurso CSV para '{slug}'")

    def _fetch_csv(self, slug: str) -> str:
        import httpx
        url = self._resolve_csv(slug)
        with httpx.Client(timeout=120, follow_redirects=True, headers=_HEADERS) as http:
            return http.get(url).content.decode("latin-1")

    def generation_shares(self) -> Dict[int, Dict[str, float]]:
        """Validated technology shares by year (see ``parse_generation_shares``)."""
        return parse_generation_shares(self._fetch_csv(SLUG_GENERATION))

    def renewable_penetration(self) -> Dict[int, float]:
        """``{year: renewable_share_pct}`` over the clean years."""
        return renewable_share_by_year(self.generation_shares())


generation_client = GenerationMixClient()
