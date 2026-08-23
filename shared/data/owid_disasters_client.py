"""OWID disasters connector — realized climate-disaster mortality per country.

Our World in Data publishes EM-DAT (CRED) disaster death rates per 100k people,
by type, country-year (CC-BY). We use the CLIMATE-related types (drought, flood,
landslide, extreme weather, wildfire, extreme temperature — excluding seismic/
volcanic) as the realized OUTCOME to backtest the IRC: a less climate-resilient
country (lower IRC) should suffer higher climate-disaster mortality.
"""
import csv
import io
import logging
import statistics
from typing import Dict, List, Optional

logger = logging.getLogger("sdq.data.owid_disasters")

_CSV_URL = ("https://ourworldindata.org/grapher/natural-disaster-death-rates.csv"
            "?csvType=full&useColumnShortNames=true")
_HEADERS = {"User-Agent": "Mozilla/5.0 (SDQ-MIP)"}

# Climate-related death-rate columns (per 100k, yearly). Earthquake & volcanic
# are excluded — they are not climate hazards.
_CLIMATE_COLS = (
    "total_dead_per_100k_people_drought_yearly",
    "total_dead_per_100k_people_flood_yearly",
    "total_dead_per_100k_people_landslide_yearly",
    "total_dead_per_100k_people_extreme_weather_yearly",
    "total_dead_per_100k_people_wildfire_yearly",
    "total_dead_per_100k_people_extreme_temperature_yearly",
)


def parse_climate_mortality(
    csv_text: str, iso3_list: List[str], year_from: int = 2000, year_to: int = 2100,
) -> Dict[str, float]:
    """``{iso3: mean climate-disaster deaths/100k/yr}`` over [year_from, year_to],
    restricted to *iso3_list*. A country present with no climate deaths → 0.0."""
    want = {i.upper() for i in iso3_list}
    annual: Dict[str, List[float]] = {}
    for row in csv.DictReader(io.StringIO(csv_text)):
        iso = (row.get("code") or "").upper()
        if iso not in want:
            continue
        try:
            year = int(row["year"])
        except (ValueError, TypeError, KeyError):
            continue
        if not (year_from <= year <= year_to):
            continue
        total = 0.0
        for col in _CLIMATE_COLS:
            v = row.get(col)
            if v not in (None, ""):
                try:
                    total += float(v)
                except ValueError:
                    pass
        annual.setdefault(iso, []).append(total)
    return {iso: round(statistics.mean(vs), 4) for iso, vs in annual.items() if vs}


class OWIDDisastersClient:
    source = "OWID / EM-DAT"
    # La licencia CC-BY-4.0 es la de OWID sobre SU procesamiento; el dato de abajo es de
    # EM-DAT y no es CC. La cadena decía "CC-BY-4.0 (Our World in Data; EM-DAT/CRED)", que
    # es la licencia del redistribuidor con el nombre del productor pegado al lado — y así
    # se perdía la cláusula que restringe. Verificado el 2026-08-22:
    #   · doc.emdat.be/docs/legal/terms-of-use: acceso libre para uso NO COMERCIAL; el uso
    #     comercial exige un acuerdo aparte con CRED/UCLouvain y una cuota anual, y prohíbe
    #     construir bases sustitutas o derivadas;
    #   · la propia página de OWID lo dice: el dato de terceros queda sujeto a los términos
    #     del proveedor original.
    # El texto nombra la cláusula porque `license_restricts_redistribution` la busca ACÁ.
    license = ("OWID CC-BY-4.0 sobre su procesamiento; el dato base es de EM-DAT/CRED "
               "(UCLouvain) y NO es CC: uso NO COMERCIAL, el comercial exige acuerdo "
               "aparte con CRED — https://doc.emdat.be/docs/legal/terms-of-use/")
    # Queda en True y NO se toca acá: hoy este dato solo alimenta el backtest interno del
    # IRC (`modules.esg_climate.operations`), que no se redistribuye. Ponerlo en False
    # apagaría ese backtest sin que nadie lo haya decidido. Lo que SÍ hace falta decidir
    # —y es del dueño, no de este archivo— es si el uso comercial de la plataforma alcanza
    # a este insumo; mientras tanto la cláusula está escrita donde se lee.
    license_ok = True

    def fetch_climate_mortality(
        self, iso3_list: List[str], year_from: int = 2000,
    ) -> Dict[str, float]:
        """Download OWID death rates and return mean climate mortality per country.
        Raises on network failure (caller treats the backtest as best-effort)."""
        import httpx

        with httpx.Client(timeout=60, follow_redirects=True, headers=_HEADERS) as http:
            text = http.get(_CSV_URL).text
        return parse_climate_mortality(text, iso3_list, year_from=year_from)


owid_disasters_client = OWIDDisastersClient()
