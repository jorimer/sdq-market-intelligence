"""Cobertura educativa neta POR PROVINCIA — MINERD (SIIE, tablero Power BI).

La tasa neta de cobertura no es un dato de la ONE: lo produce el MINERD y la ONE lo
republicaba en una planilla del portal. Cuando ese portal quedó tras un desafío de
Cloudflare, la serie se cortó — y con ella la única vía al desglose provincial del eje
educativo. Este conector va a la fuente.

El tablero es un *publish to web* de Power BI, el mismo patrón que ya alimenta a TSS,
DGA y SIS en este repo: :mod:`shared.data.powerbi` resuelve el clúster, el ``modelId`` y
la decodificación del DSR, y acá solo queda la consulta y la proyección. Es una API
interna no documentada y por lo tanto frágil: **todo falla cerrado** (excepción con
motivo, nunca dato inventado).

Qué mejora respecto de la planilla que se rompió:

* viene del productor y no de la republicación;
* llega al año lectivo 2024-2025 (la planilla se quedaba en 2024);
* trae los cuatro niveles y **provincia y región en la misma fila**, sin depender de un
  parser de layout de Excel que un cambio de columnas podía descolocar en silencio.

Dos normalizaciones, ambas heredadas del parser anterior para que la serie sea
continua: el año lectivo ``A-B`` se estampa al año calendario ``B``, y el nivel de
secundaria admite ``Secundario`` y ``Medio`` (la etiqueta previa a 2014).

El tablero mezcla filas de agregado —totales de país y de región— entre las
provinciales. No se filtran por nombre: se resuelven contra el padrón de
:mod:`shared.reference.provinces`, que rechaza y registra lo que no reconoce. Una lista
negra de etiquetas envejece mal; el padrón es la misma verdad que usa el resto del eje.
"""
from __future__ import annotations

import logging
import re
from typing import List, Optional, Tuple

logger = logging.getLogger("sdq.data.minerd_coverage")

# Tablero «Indicadores de cobertura» del SIIE (siie.minerd.gob.do/tableros-de-informacion).
VIEW_TOKEN = ("eyJrIjoiMzQyNWM1OGEtMjEwMS00NDNiLTk0NGEtYzg1NWI5YmQ1N2M2IiwidCI6IjY2ZTI4"
              "OThiLTJjMzUtNDMzZi1hNzUzLWJkNjRhY2EzOWFmYiIsImMiOjF9")
VIEW_URL = "https://app.powerbi.com/view?r=" + VIEW_TOKEN

SOURCE = "MINERD"
LICENSE = "estadísticas públicas del Ministerio de Educación (SIIE) — uso con cita"

ENTITY = "Data 2"
P_YEAR, P_LEVEL, P_PROVINCE, P_REGION, P_COVERAGE = (
    "Año", "Nivel", "Provincia", "Región", "Cobertura")
_WINDOW = 30000          # filas máximas por consulta (el tablero tiene ~1.2k)

# Niveles que cuentan como secundaria. "Medio" es la etiqueta previa a 2014 y se acepta
# por continuidad con la serie que traía la ONE.
SECONDARY_LEVELS = ("secundario", "medio")

_SCHOOL_YEAR = re.compile(r"^\s*((?:19|20)\d{2})\s*-\s*((?:19|20)\d{2})\s*$")


class MinerdCoverageError(RuntimeError):
    """El tablero no se pudo leer o cambió de estructura. Lleva el motivo."""


def school_year_to_calendar(label: object) -> Optional[int]:
    """``'2023-2024'`` → ``2024``. Misma convención que el parser anterior, para que la
    serie no se corte ni se duplique al cambiar de fuente. Un año lectivo cuyo segundo
    tramo no sigue al primero se descarta: es un error de origen, no un período."""
    m = _SCHOOL_YEAR.match(str(label or ""))
    if not m:
        return None
    a, b = int(m.group(1)), int(m.group(2))
    return b if b == a + 1 else None


def _is_region_total(label: object) -> bool:
    """¿La etiqueta de provincia marca el agregado de su región?

    El emisor escribe ``TOTAL REGION``; se acepta con o sin acento y con espaciado
    variable, pero NO cualquier cosa que empiece con "total" — el total de país usa la
    misma primera palabra y no es un valor regional."""
    n = " ".join(str(label or "").casefold().replace("ó", "o").split())
    return n in ("total region", "total regional", "total de la region")


def _to_float(v: object) -> Optional[float]:
    """El DSR devuelve el mismo campo unas veces como número y otras como texto."""
    try:
        f = float(str(v).strip())
    except (TypeError, ValueError):
        return None
    return f if 0.0 <= f <= 100.0 else None


def build_query(model_id: int) -> dict:
    """Cuerpo de ``querydata``: cobertura por año × nivel × provincia × región."""
    def col(prop: str) -> dict:
        return {"Column": {"Expression": {"SourceRef": {"Source": "q"}}, "Property": prop}}

    return {
        "version": "1.0.0",
        "queries": [{
            "Query": {"Commands": [{"SemanticQueryDataShapeCommand": {
                "Query": {
                    "Version": 2,
                    "From": [{"Name": "q", "Entity": ENTITY, "Type": 0}],
                    "Select": [
                        {**col(P_YEAR), "Name": "q.year"},
                        {**col(P_LEVEL), "Name": "q.level"},
                        {**col(P_PROVINCE), "Name": "q.province"},
                        {**col(P_REGION), "Name": "q.region"},
                        {**col(P_COVERAGE), "Name": "q.coverage"},
                    ],
                },
                "Binding": {
                    "Primary": {"Groupings": [{"Projections": [0, 1, 2, 3, 4]}]},
                    "DataReduction": {"DataVolume": 4,
                                      "Primary": {"Window": {"Count": _WINDOW}}},
                    "Version": 1,
                },
            }}]},
            "QueryId": "",
            "ApplicationContext": {"DatasetId": "x", "Sources": [{"ReportId": "x"}]},
        }],
        "cancelQueries": [],
        "modelId": model_id,
    }


def parse_coverage_rows(rows: List[List[object]],
                        levels: Tuple[str, ...] = SECONDARY_LEVELS
                        ) -> List[Tuple[str, str, int, float]]:
    """Filas crudas del DSR → ``[('provincia', slug, año, cobertura)]``.

    Devuelve LOS DOS niveles geográficos. Las filas de agregado regional —donde la
    columna de provincia dice ``TOTAL REGION``— llevan el valor de la región en la misma
    fila, así que la serie regional se recupera del mismo productor en vez de perderse
    con la planilla de la ONE. Promediar provincias para reconstruirla habría sido
    inventar un dato: sin ponderar por población escolar, ese promedio no es la cobertura
    de la región.

    Pura (sin red) para poder fijarla en tests. Descarta —contándolo— la fila cuyo
    nivel no interesa, cuyo año lectivo no es válido, cuya cobertura cae fuera de
    0-100, o cuya etiqueta no resuelve ni a provincia ni a región del padrón (el total
    de país entra por ahí)."""
    from shared.data.one_client import region_slug
    from shared.reference.provinces import province_slug

    out: List[Tuple[str, str, int, float]] = []
    unknown: set = set()
    dropped = 0
    wanted = tuple(lv.casefold() for lv in levels)
    for row in rows:
        if len(row) < 5:
            dropped += 1
            continue
        year_label, level, province, region, coverage = row[:5]
        if not any(w in str(level or "").casefold() for w in wanted):
            continue
        year = school_year_to_calendar(year_label)
        value = _to_float(coverage)
        if year is None or value is None:
            dropped += 1
            continue
        slug = province_slug(province)
        if slug is not None:
            out.append(("provincia", slug, year, round(value, 2)))
            continue
        # No es provincia: puede ser el agregado de su región (o el total de país).
        if _is_region_total(province):
            rslug = region_slug(region)
            if rslug is not None:
                out.append(("region", rslug, year, round(value, 2)))
                continue
        if str(province or "").strip():
            unknown.add(str(province).strip())
    if unknown:
        # Acá cae "TOTAL PAIS". Se registra igual, porque una provincia nueva que dejara
        # de reconocerse aparecería en la MISMA lista y en silencio se perdería.
        logger.info("[MINERD] etiquetas no geográficas descartadas: %s", sorted(unknown))
    if dropped:
        logger.info("[MINERD] %d filas descartadas (año, nivel o valor inválido)", dropped)
    if not out:
        raise MinerdCoverageError(
            f"el tablero no devolvió ninguna fila utilizable para los niveles {levels}")
    return out


def fetch_minerd_coverage() -> List[Tuple[str, str, int, float]]:  # pragma: no cover - network I/O
    """Live: resuelve el tablero, consulta y proyecta → filas de cobertura provincial."""
    import httpx

    from shared.data import powerbi

    try:
        api = powerbi.resolve_api_host(VIEW_URL)
        res_key = powerbi.resource_key(VIEW_TOKEN)
        with httpx.Client(timeout=120, follow_redirects=True,
                          headers=powerbi.browser_headers()) as client:
            model_id = powerbi.fetch_model_id(client, api, res_key)
            resp = client.post(
                f"{api}/public/reports/querydata?synchronous=true",
                headers=powerbi.api_headers(res_key), json=build_query(model_id))
            resp.raise_for_status()
            rows = powerbi.decode_dsr_rows(resp.json(), min_cols=5)
    except powerbi.PowerBIError as e:
        raise MinerdCoverageError(f"el tablero del SIIE cambió o no respondió: {e}")
    except httpx.HTTPError as e:
        raise MinerdCoverageError(
            f"no se pudo consultar el tablero del SIIE ({type(e).__name__}: {e})")
    return parse_coverage_rows(rows)
