"""Tourism arrivals connector — DR non-resident arrivals (Eje Turismo).

Public open data from the **Oficina Nacional de Estadística (ONE)**, dataset "Llegada de
Pasajeros Vía Aérea por Año y Sexo" on the national open-data portal (datos.gob.do, CKAN).
It is a clean yearly series (1999–) of air arrivals broken down by nationality category
(residents/non-residents, foreigners/Dominicans) and by ~80 origin markets (countries and
top-level world regions) — the authoritative base for a tourism-demand traction index.

The dataset's category column mixes three layers in one list:
  * **summary** rows — "Dominicanos residentes", "Extranjeros residentes",
    "Dominicanos no residentes", "Extranjeros no residentes";
  * **region** rows — "América del norte", "Europa", … (the 7 top-level world regions,
    which sum to exactly the "Extranjeros no residentes" total — verified, mutually
    exclusive, no double counting);
  * **country** rows — "Estados Unidos", "Canadá", … (sub-components of the regions).
We derive only the unambiguous measures: non-resident arrivals (the headline tourist
count = Dominican + foreign non-residents), foreign non-resident arrivals (the pure
international tourist), and the region mix (for a clean market-diversification signal).
Country rows and "Otros …" sub-rows are NOT summed, to avoid overlapping the regions.

CSV URLs change when ONE republishes, so we resolve the current CSV resource via the
CKAN ``package_show`` API, then fetch it. The file is UTF-8 (BOM) and comma-separated.
"""
import csv
import io
import logging
import unicodedata
from typing import Dict, Optional

logger = logging.getLogger("sdq.data.tourism")

_CKAN = "https://datos.gob.do/api/3/action/package_show"
_HEADERS = {"User-Agent": "Mozilla/5.0 (SDQ-MIP)"}

SLUG_ARRIVALS = "llegada-de-pasajeros-via-aerea"

# Non-resident summary categories (the headline tourist count). "Dominicanos no
# residentes" (diaspora) + "Extranjeros no residentes" (foreign tourists).
_DOM_NONRES = "dominicanos no residentes"
_FOREIGN_NONRES = "extranjeros no residentes"

# The 7 mutually-exclusive top-level world regions. Their sum equals the foreign
# non-resident total each year (verified), so HHI over them is a clean concentration
# signal without double counting countries.
_REGIONS = {
    "america del norte": "América del Norte",
    "america central y caribe": "América Central y Caribe",
    "america del sur": "América del Sur",
    "europa": "Europa",
    "asia": "Asia",
    "australia": "Australia",
    "resto del mundo": "Resto del Mundo",
}


def _norm(s: str) -> str:
    t = "".join(c for c in unicodedata.normalize("NFKD", (s or "").lower())
                if not unicodedata.combining(c))
    return " ".join(t.split())


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


def parse_arrivals(text: str) -> Dict[int, Dict[str, object]]:
    """``{year: {nonresident, foreign, regions:{display: value}}}`` from the ONE CSV.

    Sums over the sex breakdown. Only the unambiguous, non-overlapping categories are
    kept (summary non-residents + the 7 top-level regions). Empty cells stay absent
    (never fabricated)."""
    reader = csv.reader(io.StringIO(text.lstrip("﻿")))
    header = next(reader, None)
    if not header:
        return {}
    cat_col = nat_col = val_col = year_col = None
    for i, h in enumerate(header):
        n = _norm(h)
        if "nacionalidad" in n and "total" not in n:
            cat_col = i
        elif n == "sexo":
            nat_col = i  # noqa: F841 — sex is summed over, column located for clarity
        elif "total" in n:
            val_col = i
        elif n in ("ano", "anio"):
            year_col = i
    if cat_col is None or val_col is None or year_col is None:
        return {}

    out: Dict[int, Dict[str, object]] = {}
    for row in reader:
        if len(row) <= max(cat_col, val_col, year_col):
            continue
        ys = row[year_col].strip()
        if not (len(ys) == 4 and ys.isdigit()):
            continue
        year = int(ys)
        value = _num(row[val_col])
        if value is None:
            continue
        cat = _norm(row[cat_col])
        rec = out.setdefault(year, {"nonresident": 0.0, "foreign": 0.0, "regions": {}})
        if cat == _DOM_NONRES:
            rec["nonresident"] = float(rec["nonresident"]) + value  # type: ignore[arg-type]
        elif cat == _FOREIGN_NONRES:
            rec["nonresident"] = float(rec["nonresident"]) + value  # type: ignore[arg-type]
            rec["foreign"] = float(rec["foreign"]) + value  # type: ignore[arg-type]
        elif cat in _REGIONS:
            display = _REGIONS[cat]
            regions = rec["regions"]  # type: ignore[assignment]
            regions[display] = regions.get(display, 0.0) + value  # type: ignore[union-attr]
    # Drop years with no non-resident total (defensive; never fabricate).
    return {y: r for y, r in out.items() if float(r["nonresident"]) > 0}  # type: ignore[arg-type]


class TourismArrivalsClient:
    source = "ONE (Oficina Nacional de Estadística)"
    license = "Datos Abiertos RD (datos.gob.do)"
    license_ok = True

    def _resolve_csv(self, slug: str) -> str:
        import httpx
        with httpx.Client(timeout=60, follow_redirects=True, headers=_HEADERS) as http:
            data = http.get(_CKAN, params={"id": slug}).json()
        for r in (data.get("result") or {}).get("resources", []):
            if (r.get("format") or "").upper() == "CSV" and r.get("url"):
                return r["url"]
        raise RuntimeError(f"Turismo: sin recurso CSV para '{slug}'")

    def _fetch_csv(self, slug: str) -> str:
        import httpx
        url = self._resolve_csv(slug)
        with httpx.Client(timeout=120, follow_redirects=True, headers=_HEADERS) as http:
            return http.get(url).content.decode("utf-8-sig")

    def arrivals(self) -> Dict[int, Dict[str, object]]:
        return parse_arrivals(self._fetch_csv(SLUG_ARRIVALS))


tourism_arrivals_client = TourismArrivalsClient()
