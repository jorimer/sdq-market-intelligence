"""HURDAT2 connector — national hurricane exposure (NOAA Atlantic best-track).

NOAA NHC's HURDAT2 is the authoritative Atlantic-basin storm database (1851-),
public domain. We replicate the standard exposure approach (cf. the R package
geanders/hurricaneexposure, which is US-county-only): count storms whose track
passes within a buffer of each country's hurricane-relevant reference point,
weighted by intensity, over a recent window → a real, comparable national
hurricane-exposure metric. Feeds the IRC physical-risk dimension (Gate B).

Atlantic-only by nature: Caribbean/Gulf-facing countries score high; Pacific or
southern-cone countries score ~0 — which is correct (they get no Atlantic
hurricanes), not missing data.
"""
import logging
import math
import re
from typing import Dict, List, Optional, Tuple

logger = logging.getLogger("sdq.data.hurdat2")

_INDEX_URL = "https://www.nhc.noaa.gov/data/hurdat/"
_HEADERS = {"User-Agent": "Mozilla/5.0 (SDQ-MIP)"}
_TS_KT = 34          # tropical-storm threshold (kt); below = depression, ignored
_WINDOW_YEARS = 30   # recent climatology window
_BUFFER_KM = 500.0   # a storm within this of the ref point "affects" the country

# Hurricane-relevant reference point per country (lat, lon): the Caribbean/Atlantic/
# Gulf-facing population or coast centroid — NOT the geographic centroid, so the
# Atlantic-only basin is read where it actually makes landfall. Pacific/southern
# countries use their centroid (→ ~0 Atlantic exposure, correct).
COUNTRY_REFS: Dict[str, Tuple[float, float]] = {
    "DOM": (18.7, -70.2), "HTI": (19.0, -72.4), "JAM": (18.1, -77.3),
    "TTO": (10.5, -61.3), "GUY": (6.8, -58.2), "SUR": (4.0, -56.0),
    "BLZ": (17.2, -88.5), "CRI": (10.0, -83.5), "PAN": (9.4, -79.9),
    "GTM": (15.7, -89.5), "SLV": (13.8, -88.9), "HND": (15.5, -86.5),
    "NIC": (12.9, -83.7), "MEX": (20.0, -90.0), "COL": (10.4, -75.5),
    "VEN": (10.6, -66.9), "ECU": (-1.5, -78.5), "PER": (-10.0, -76.0),
    "BOL": (-17.0, -65.0), "CHL": (-33.0, -71.0), "ARG": (-34.0, -64.0),
    "BRA": (-10.0, -52.0), "PRY": (-23.0, -58.0), "URY": (-33.0, -56.0),
}


def _haversine(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Great-circle distance in km."""
    r = 6371.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp, dl = math.radians(lat2 - lat1), math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(min(1.0, math.sqrt(a)))


def _coord(token: str) -> Optional[float]:
    """``"18.7N"`` → 18.7 ; ``"70.2W"`` → -70.2."""
    m = re.match(r"^\s*([0-9.]+)\s*([NSEW])\s*$", token)
    if not m:
        return None
    v = float(m.group(1))
    return -v if m.group(2) in ("S", "W") else v


def parse_hurdat2(text: str) -> List[Dict]:
    """Parse HURDAT2 text → ``[{year, max_wind, track:[(lat,lon)]}]`` (TS+ only)."""
    storms: List[Dict] = []
    cur: Optional[Dict] = None
    for line in text.splitlines():
        parts = [p.strip() for p in line.split(",")]
        if not parts or not parts[0]:
            continue
        if re.match(r"^[A-Z]{2}\d{6}$", parts[0]):            # header: id,name,npoints
            if cur and cur["track"] and cur["max_wind"] >= _TS_KT:
                storms.append(cur)
            cur = {"year": int(parts[0][4:8]), "max_wind": 0, "track": []}
        elif cur is not None and len(parts) >= 7:             # track point
            lat, lon = _coord(parts[4]), _coord(parts[5])
            try:
                wind = int(parts[6])
            except ValueError:
                wind = -999
            if lat is not None and lon is not None:
                cur["track"].append((lat, lon))
                if wind > cur["max_wind"]:
                    cur["max_wind"] = wind
    if cur and cur["track"] and cur["max_wind"] >= _TS_KT:
        storms.append(cur)
    return storms


def hurricane_exposure(
    iso3_list: List[str], storms: List[Dict], latest_year: int,
    window_years: int = _WINDOW_YEARS, buffer_km: float = _BUFFER_KM,
) -> Dict[str, float]:
    """``{iso3: exposure}`` — annualized intensity-weighted count of TS+ storms
    passing within *buffer_km* of the country's reference point over the window.

    Higher = more exposed. A known country (in COUNTRY_REFS) with no qualifying
    storms gets 0.0 (real: no Atlantic hurricanes), never omitted."""
    cutoff = latest_year - window_years + 1
    recent = [s for s in storms if s["year"] >= cutoff]
    out: Dict[str, float] = {}
    for iso3 in iso3_list:
        ref = COUNTRY_REFS.get(iso3.upper())
        if ref is None:
            continue
        total = 0.0
        for s in recent:
            if any(_haversine(ref[0], ref[1], la, lo) <= buffer_km for la, lo in s["track"]):
                total += s["max_wind"]            # weight by peak intensity (kt)
        out[iso3.upper()] = round(total / window_years, 2)
    return out


class HURDAT2Client:
    source = "HURDAT2"
    license = "NOAA NHC — dominio público"
    license_ok = True

    def latest_file_url(self, index_html: str) -> Optional[str]:
        """Newest ``hurdat2-1851-YYYY-MMDDYY.txt`` from the NHC directory listing."""
        names = re.findall(r"hurdat2-1851-(\d{4})-(\d{6})\.txt", index_html)
        if not names:
            return None
        best = max(names, key=lambda yr_rel: (int(yr_rel[0]), int(yr_rel[1])))
        return f"{_INDEX_URL}hurdat2-1851-{best[0]}-{best[1]}.txt"

    def fetch_exposure(self, iso3_list: List[str]) -> Tuple[Dict[str, float], Optional[int]]:
        """Download the latest HURDAT2, parse and compute exposure per country.
        Returns ``({iso3: exposure}, latest_year)``. Raises on network failure
        (the caller treats Gate B as best-effort)."""
        import httpx

        with httpx.Client(timeout=90, follow_redirects=True, headers=_HEADERS) as http:
            url = self.latest_file_url(http.get(_INDEX_URL).text)
            if not url:
                raise ValueError("HURDAT2: no se encontró el archivo en el índice de NHC")
            text = http.get(url).text
        storms = parse_hurdat2(text)
        latest_year = max((s["year"] for s in storms), default=0)
        return hurricane_exposure(iso3_list, storms, latest_year), latest_year


hurdat2_client = HURDAT2Client()
