"""ITU DataHub connector — DR telecom indicators (reemplazo vigente de INDOTEL).

INDOTEL congeló su boletín público en 2022-Q1 (ver ``indotel_client``); la base
World Telecommunication/ICT Indicators de la UIT se discontinuó en 2024 y AHORA es
ABIERTA (Creative Commons) en ITU DataHub. Su API REST pública v2 entrega series por
indicador y país en JSON, fresca hasta 2024.

    GET https://api.datahub.itu.int/v2/data/bycode/{code}/byiso/DOM

Códigos (del catálogo ITU, verificados contra el explorador):
  260   Total population (denominador)
  178   Mobile-cellular subscriptions (conteo)
  11632 Active mobile-broadband subscriptions (conteo)
  19303 Fixed-broadband subscriptions (TASA por 100 hab.)
  12047 Households with Internet access at home (%)

El IDT se reconstruye sobre PENETRACIÓN (per-100/%), estándar y comparable: móvil y
banda ancha móvil se derivan de conteo/población; banda ancha fija viene per-100. El
sitio bloquea bots sin User-Agent (473) → se envía UA de navegador. Nunca fabricado.
"""
import logging
from typing import Any, Dict, Optional

logger = logging.getLogger("sdq.data.itu")

_BASE = "https://api.datahub.itu.int/v2/data/bycode/{code}/byiso/DOM"
_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                  "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36",
    "Accept": "application/json",
}

CODE_POPULATION = 260
CODE_MOBILE = 178             # conteo de suscripciones móvil-celular
CODE_MOBILE_BROADBAND = 11632  # conteo de banda ancha móvil activa
CODE_FIXED_BROADBAND = 19303   # banda ancha fija POR 100 habitantes
CODE_HH_INTERNET = 12047       # hogares con internet (%)


def _series(payload: Any) -> Dict[int, float]:
    """``[{dataYear, answer:[{value}]}]`` → ``{year: value}`` (descarta nulos)."""
    out: Dict[int, float] = {}
    for r in payload if isinstance(payload, list) else []:
        year = r.get("dataYear")
        ans = (r.get("answer") or [{}])
        val = ans[0].get("value") if ans else None
        if year is None or val is None:
            continue
        try:
            out[int(year)] = float(val)
        except (TypeError, ValueError):
            continue
    return out


def parse_indicators(by_code: Dict[int, Dict[int, float]]) -> Dict[str, Any]:
    """De ``{code: {year: value}}`` deriva las penetraciones del año más reciente con
    dato de telecom (móvil). La población se toma de ese mismo año (o el más cercano).
    Devuelve penetraciones per-100/% — listas para el IDT. Missing → None."""
    mobile = by_code.get(CODE_MOBILE, {})
    if not mobile:
        return {"period": None, "mobile_penetration": None,
                "mobile_broadband_penetration": None, "fixed_broadband_penetration": None,
                "households_internet": None, "population": None}
    year = max(mobile)
    pop_series = by_code.get(CODE_POPULATION, {})

    def _pop(y: int) -> Optional[float]:
        if not pop_series:
            return None
        return pop_series.get(y) or pop_series[max(pop_series)]

    def _latest(code: int) -> Optional[float]:
        s = by_code.get(code, {})
        return s.get(year) or (s[max(s)] if s else None)

    pop = _pop(year)
    mob = mobile.get(year)
    mobbb = _latest(CODE_MOBILE_BROADBAND)
    fixedbb_p100 = _latest(CODE_FIXED_BROADBAND)  # ya es per-100
    hh = _latest(CODE_HH_INTERNET)

    def _pen(count: Optional[float]) -> Optional[float]:
        return round(count / pop * 100, 1) if (count is not None and pop) else None

    return {
        "period": str(year),
        "mobile_penetration": _pen(mob),
        "mobile_broadband_penetration": _pen(mobbb),
        "fixed_broadband_penetration": round(fixedbb_p100, 1) if fixedbb_p100 is not None else None,
        "households_internet": round(hh, 1) if hh is not None else None,
        "population": int(pop) if pop else None,
    }


class ITUClient:
    source = "ITU DataHub"
    license = "CC BY-NC-SA 3.0 IGO (ITU)"
    license_ok = True
    codes = (CODE_POPULATION, CODE_MOBILE, CODE_MOBILE_BROADBAND,
             CODE_FIXED_BROADBAND, CODE_HH_INTERNET)

    def fetch_indicators(self) -> Dict[str, Any]:
        """Descarga los indicadores de penetración telecom de RD de la API ITU v2.

        ``{period, mobile_penetration, mobile_broadband_penetration,
        fixed_broadband_penetration, households_internet, population}``. Levanta en
        fallo de red (el sync es best-effort)."""
        import httpx

        by_code: Dict[int, Dict[int, float]] = {}
        with httpx.Client(timeout=60, follow_redirects=True, headers=_HEADERS) as http:
            for code in self.codes:
                resp = http.get(_BASE.format(code=code))
                resp.raise_for_status()
                by_code[code] = _series(resp.json())
        return parse_indicators(by_code)


itu_client = ITUClient()
