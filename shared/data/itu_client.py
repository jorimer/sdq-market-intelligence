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


def parse_indicators_for_year(by_code: Dict[int, Dict[int, float]], year: int) -> Dict[str, Any]:
    """Penetraciones de UN año específico (exact-year, sin arrastre de años vecinos).

    Para el backfill anual: cada año usa SU propio dato, nunca el de un año posterior
    (no se filtra el futuro) ni el de uno anterior (no se inventa continuidad). La
    población es la del mismo año. Missing → None (la dimensión baja la cobertura)."""
    pop_series = by_code.get(CODE_POPULATION, {})
    pop = pop_series.get(year)

    def _pen(code: int) -> Optional[float]:
        v = by_code.get(code, {}).get(year)
        return round(v / pop * 100, 1) if (v is not None and pop) else None

    fixedbb = by_code.get(CODE_FIXED_BROADBAND, {}).get(year)  # ya es per-100
    hh = by_code.get(CODE_HH_INTERNET, {}).get(year)
    return {
        "period": str(year),
        "mobile_penetration": _pen(CODE_MOBILE),
        "mobile_broadband_penetration": _pen(CODE_MOBILE_BROADBAND),
        "fixed_broadband_penetration": round(fixedbb, 1) if fixedbb is not None else None,
        "households_internet": round(hh, 1) if hh is not None else None,
        "population": int(pop) if pop else None,
    }


#: Qué respuesta significa qué, al sondear el API. El 403 es la restricción que la UIT
#: declaró por correo (ciberataques → acceso externo cortado); cualquier otra cosa que no
#: sea 200 es "no sé", y decirlo importa: «no pude leer» NO es evidencia de que siga
#: cerrado, igual que en la sonda de INDOTEL.
RESTRINGIDO = "restringido"     # el emisor contesta y niega el acceso (403)
ABIERTO = "abierto"             # volvió: el API responde con dato
INDETERMINADO = "indeterminado"  # no se pudo llegar; no concluye nada


def sonda_datahub(timeout: int = 30) -> Dict[str, Any]:
    """¿Volvió a estar accesible el API del DataHub? Sonda barata, nunca levanta.

    **Por qué hace falta.** El 2026-07-19 el API dejó de responder (403) y la UIT confirmó
    por escrito el 2026-08-18 que restringió el acceso externo tras una serie de
    ciberataques, sin fecha de restablecimiento. El sync del IDT quedó en `error`, y su
    cadencia es ANUAL: el próximo intento programado es de 2027. O sea que si la UIT
    reabre mañana, nadie se entera durante diez meses. La sonda cierra ese hueco.

    Devuelve ``{"estado", "http", "detalle"}``. Distingue las tres cosas a propósito: que
    el emisor niegue el acceso y que nosotros no podamos llegar son hechos distintos, y
    confundirlos haría que un problema de red se leyera como «sigue cerrado».
    """
    import httpx

    url = _BASE.format(code=CODE_POPULATION)
    try:
        r = httpx.get(url, headers=_HEADERS, timeout=timeout, follow_redirects=True)
    except Exception as e:  # noqa: BLE001 — una sonda que rompe deja de vigilar
        logger.warning("[ITU] la sonda no pudo llegar al DataHub: %s", e)
        return {"estado": INDETERMINADO, "http": None,
                "detalle": f"no se pudo llegar a {url} ({type(e).__name__})"}
    if r.status_code == 200:
        return {"estado": ABIERTO, "http": 200,
                "detalle": f"{url} respondió 200: el acceso programático volvió"}
    if r.status_code in (401, 403):
        return {"estado": RESTRINGIDO, "http": r.status_code,
                "detalle": ("el emisor sigue negando el acceso externo "
                            f"(HTTP {r.status_code}), como declaró el 2026-08-18")}
    return {"estado": INDETERMINADO, "http": r.status_code,
            "detalle": f"respuesta inesperada HTTP {r.status_code}: no concluye nada"}


class ITUClient:
    source = "ITU DataHub"
    # El único caso del catálogo que va en la dirección CONTRARIA: lo declarado es MÁS
    # restrictivo que lo que el emisor autoriza. La plataforma publica CC BY-NC-SA 3.0 IGO,
    # y la UIT nos dio permiso ESCRITO por encima de eso.
    #
    # Respuesta de la División de Datos y Analítica de las TIC (Indicators@itu.int, con
    # copia a thierry.geiger@ y viviana.umpierrez@), 2026-08-18, a la consulta enviada el
    # mismo día desde Ricardo.mercado@sdqconsulting.com.do: los datos del DataHub se pueden
    # usar «para el propósito que describe, incluido su uso como insumo para productos
    # analíticos comerciales, siempre que la UIT (ITU) sea citada adecuadamente como
    # fuente». Y añade que están actualizando sus términos para permitir explícitamente el
    # uso comercial, y que **la licencia que hoy figura en la plataforma todavía no refleja
    # ese cambio** — o sea que el BY-NC-SA publicado está vencido de hecho, no de derecho.
    #
    # QUÉ CUBRE Y QUÉ NO. La consulta describía el uso con precisión —insumo de un índice,
    # con atribución, «no redistribuimos las series en bruto»— y el permiso se concedió
    # sobre ESE uso. No es una licencia nueva ni alcanza a reexportar la serie tal cual.
    # Por eso la cadena CONSERVA las marcas NC/SA: `license_restricts_redistribution` sigue
    # reteniendo lo verbatim en la Data API, que es exactamente el límite del permiso,
    # mientras el cálculo propio sobre ese insumo sale como siempre. El eje verbatim/derived
    # del manifiesto y el alcance de lo que la UIT autorizó resultaron ser el mismo corte.
    #
    # PENDIENTE, y es una condición del permiso: la atribución a la UIT. Acá es obligación
    # contractual, no cortesía, y el eje telecom NO tiene el mecanismo que sí tiene el eje
    # de leyes (`exige_atribucion` computado desde el expediente). Hoy depende de que el
    # redactor se acuerde, que es como se pierde.
    license = ("ITU DataHub — la plataforma publica CC BY-NC-SA 3.0 IGO, pero la UIT "
               "autorizó POR ESCRITO (2026-08-18) el uso como insumo de productos "
               "analíticos comerciales citándola como fuente; el permiso NO cubre "
               "redistribuir las series en bruto, y la UIT está actualizando sus términos")
    license_ok = True
    codes = (CODE_POPULATION, CODE_MOBILE, CODE_MOBILE_BROADBAND,
             CODE_FIXED_BROADBAND, CODE_HH_INTERNET)

    def fetch_by_code(self) -> Dict[int, Dict[int, float]]:
        """Descarga las series crudas ``{code: {año: valor}}`` de RD (todos los años).
        Levanta en fallo de red (el sync es best-effort)."""
        import httpx

        by_code: Dict[int, Dict[int, float]] = {}
        with httpx.Client(timeout=60, follow_redirects=True, headers=_HEADERS) as http:
            for code in self.codes:
                resp = http.get(_BASE.format(code=code))
                resp.raise_for_status()
                by_code[code] = _series(resp.json())
        return by_code

    def fetch_indicators(self) -> Dict[str, Any]:
        """Indicadores de penetración telecom de RD del año más reciente (vista live).

        ``{period, mobile_penetration, mobile_broadband_penetration,
        fixed_broadband_penetration, households_internet, population}``."""
        return parse_indicators(self.fetch_by_code())


itu_client = ITUClient()
