"""SPEC-6 — comparación regional (Centroamérica + Caribe) desde WDI.

La brecha original del motor: una pregunta como "…y cómo se compara con el promedio de Centroamérica
y el Caribe" no tenía capacidad de benchmark regional. Este módulo la cubre reusando el panel del
IRMP (``shared.data.latam_peers``) y el WDI del Banco Mundial.

**Límite de honestidad (decisión del dueño 2026-07-15):** el WDI solo desagrega el valor agregado por
GRAN-sector cross-country (agricultura / industria / servicios) + crecimiento del PIB. NO existe
minería, turismo ni construcción por separado para la mayoría de los pares. Por eso entregamos la
gran-composición + el crecimiento y DECLARAMOS el límite — nunca fabricamos un "minería RD vs minería
CA" que la fuente no soporta. Si el WDI no responde, se degrada a brecha declarada (no se inventa).
"""
from __future__ import annotations

import statistics
from typing import Callable, Dict, List, Optional, Tuple

# Indicadores WDI (value added, % del PIB) — gran-composición cross-country.
WDI_COMPOSITION: Dict[str, str] = {
    "NV.AGR.TOTL.ZS": "Agricultura",
    "NV.IND.TOTL.ZS": "Industria",
    "NV.SRV.TOTL.ZS": "Servicios",
}
WDI_GDP_GROWTH = "NY.GDP.MKTP.KD.ZG"  # crecimiento del PIB real (%)

DOM_ISO3 = "DOM"
REGIONAL_SOURCE = "World Bank WDI · panel Centroamérica y el Caribe"

# Palabras que activan el benchmark regional (normalizadas, sin acentos).
REGIONAL_KEYWORDS: Tuple[str, ...] = (
    "centroamerica", "el caribe", "la region", "promedio regional", "resto de la region",
    "comparado con la region", "vs la region", "referente regional", "pares regionales",
    "america central",
)

# Fetcher: (indicator, iso3_codes, mrv) -> (rows, last_updated). Reusa el del IRMP por defecto,
# pero es inyectable para tests offline.
Fetcher = Callable[[str, List[str], int], Tuple[List[dict], Optional[str]]]


def regional_peers_iso3() -> List[str]:
    """ISO3 de Centroamérica + Caribe SIN RD (los pares contra los que se compara)."""
    from shared.data.latam_peers import PEERS
    return [p.iso3 for p in PEERS
            if p.region in ("Centroamérica", "Caribe") and p.iso3 != DOM_ISO3]


def _latest_by_country(rows: List[dict]) -> Dict[str, Tuple[int, float]]:
    """``iso3 -> (año, valor)`` del año más reciente con dato por país."""
    out: Dict[str, Tuple[int, float]] = {}
    for r in rows:
        iso, yr, val = r.get("countryiso3code"), r.get("date"), r.get("value")
        if not iso or not yr or val is None:
            continue
        y = int(yr)
        if iso not in out or y > out[iso][0]:
            out[iso] = (y, float(val))
    return out


def _default_fetcher() -> Fetcher:
    from shared.data.wdi_client import fetch_wb_indicator
    return fetch_wb_indicator


def build_regional_comparison(
    fetch: Optional[Fetcher] = None, mrv: int = 1,
) -> Optional[Dict[str, object]]:
    """RD vs promedio Centroamérica+Caribe: gran-composición (agri/industria/servicios) +
    crecimiento del PIB. Devuelve ``None`` si no se obtiene ni un indicador (→ brecha declarada,
    sin fabricar). Puro salvo por *fetch* (inyectable)."""
    fetch = fetch or _default_fetcher()
    peers = regional_peers_iso3()
    iso3_all = [DOM_ISO3] + peers
    composition: List[Dict[str, object]] = []
    year_seen: Optional[int] = None

    for code, label in WDI_COMPOSITION.items():
        try:
            rows, _pub = fetch(code, iso3_all, mrv)
        except Exception:  # noqa: BLE001 — un indicador caído no tumba el resto; si caen todos → None
            continue
        latest = _latest_by_country(rows)
        do = latest.get(DOM_ISO3)
        peer_vals = [v for iso, (_y, v) in latest.items() if iso != DOM_ISO3]
        if do is None or not peer_vals:
            continue
        year_seen = do[0] if year_seen is None else max(year_seen, do[0])
        composition.append({
            "sector": label, "dom": round(do[1], 1),
            "region_avg": round(statistics.mean(peer_vals), 1),
            "n_peers": len(peer_vals), "year": do[0],
        })

    growth: Optional[Dict[str, object]] = None
    try:
        rows, _pub = fetch(WDI_GDP_GROWTH, iso3_all, mrv)
        latest = _latest_by_country(rows)
        do = latest.get(DOM_ISO3)
        peer_vals = [v for iso, (_y, v) in latest.items() if iso != DOM_ISO3]
        if do is not None and peer_vals:
            growth = {"dom": round(do[1], 1),
                      "region_avg": round(statistics.mean(peer_vals), 1),
                      "n_peers": len(peer_vals), "year": do[0]}
    except Exception:  # noqa: BLE001
        growth = None

    if not composition and growth is None:
        return None
    return {"composition": composition, "growth": growth, "year": year_seen,
            "source": REGIONAL_SOURCE}
