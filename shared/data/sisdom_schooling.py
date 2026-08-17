"""SISDOM (MEPyD) — escolaridad promedio por región Y TOTAL PAÍS, anual 2000-2024.

Cuadro ``05 3 007`` del libro *Indicadores de educación*. Reemplaza la serie NACIONAL de
la ONE (``años promedio de educación``), que quedó tras el desafío de Cloudflare y que,
aun cuando llegaba, era **la misma cifra para las diez regiones**.

Lo que cambia no es solo la disponibilidad. Con el dato nacional la escolaridad aportaba
nivel y nunca orden; por región discrimina, y bastante: en 2016, Ozama promedia 10,32
años y El Valle 7,56 — casi tres años de diferencia que el número nacional (9,18)
escondía por completo. Es la segunda de las constantes nacionales del IDM en caer,
después del ingreso.

**Layout inverso al del cuadro de ingreso**, y por eso este parser no reusa aquel: acá
los años son COLUMNAS y las desagregaciones FILAS, así que el bloque de regionalización
se elige por fila y no por columna. Lo que sí es común —descubrir el libro, bajarlo,
abrir la hoja— vive en :mod:`shared.data.sisdom_common`.

Dos trampas del emisor, las mismas que en el resto del SISDOM:

* **Tres regionalizaciones conviven** en la hoja (Dec 710-04, Dec 685-00 y Dec 345-22).
  La de 685-00 usa otro conjunto de regiones, así que tomar "el primer bloque cuyas
  etiquetas resuelvan" daría cifras de otra regionalización sin que nada lo advirtiera.
* **Los años desde 2017 vienen asteriscados** (cambio de metodología ENFT→ENCFT).
  Descartar lo asteriscado —el error que ya cometimos una vez— corta la serie en 2016 y
  parece un problema de la fuente cuando es del parser.
"""
from __future__ import annotations

import logging
import re
from typing import Dict, List, Optional, Tuple

from shared.data.sisdom_common import (
    BLOCK_HEADER,
    LICENSE,
    REGIONALIZATIONS,
    SOURCE,
    SisdomUnavailable,
    fetch_book,
    norm,
    open_sheet,
)

logger = logging.getLogger("sdq.data.sisdom_schooling")

__all__ = ["LICENSE", "SOURCE", "UNIT", "SisdomUnavailable",
           "fetch_sisdom_schooling", "parse_schooling"]

BOOK_FRAGMENT = "indicadore de educacion"   # el título del emisor dice "Indicadore"
SHEET = "05 3 007"
INDICATOR = "Escolaridad promedio de la población de 15 años y más"
UNIT = "años de estudio (15+)"              # ≤40: sd_indicators.unit es VARCHAR(40)

_YEAR_CELL = re.compile(r"^((?:19|20)\d{2})")
_HEADER_SCAN_ROWS = 15
# Escolaridad promedio: un país no supera ~15 años de estudio medios. Fuera de rango es
# un artefacto de celda, no un dato.
_MAX_YEARS = 25.0

#: Etiqueta de la fila NACIONAL. Encabeza el bloque «Desagregaciones», por encima de las
#: tres regionalizaciones, y el parser la salteaba porque no resuelve a ninguna región.
#:
#: Es la misma historia que el `TOTAL PAIS` del tablero del MINERD: la cifra del país
#: estaba en el archivo que ya bajábamos y se perdía en el filtro. Sin ella, un consumidor
#: que compare contra una meta NACIONAL termina usando la de una región — que es lo que
#: pasó con la escolaridad del indicador 2.18 de la END.
TOTAL_LABEL = "total"
COUNTRY_SLUG = "pais"


def _year_columns(rows: List[list]) -> Dict[int, int]:
    """``{columna: año}`` de la fila de encabezado — la que trae más años.

    Acepta el asterisco del emisor (``2017*``): descartarlo cortaría la serie en 2016 y
    parecería un problema de la fuente."""
    best: Dict[int, int] = {}
    for r in rows[:_HEADER_SCAN_ROWS]:
        found: Dict[int, int] = {}
        for ci, cell in enumerate(r):
            m = _YEAR_CELL.match(str(cell).strip()) if cell is not None else None
            if m:
                found[ci] = int(m.group(1))
        if len(found) > len(best):
            best = found
    return best


def _select_block(rows: List[list], col_year: Dict[int, int]) -> Tuple[int, int]:
    """``(fila_inicio, fila_fin)`` del bloque de regionalización a usar.

    Los bloques se anuncian en su propia fila ("Regiones de desarrollo (Decreto
    710-04)") y llegan hasta el anuncio siguiente. La de 685-00 queda excluida: usa otro
    conjunto de regiones, y mezclarla produciría una serie incoherente.

    Entre las regionalizaciones ACEPTABLES gana la de **más cobertura**, no la más
    reciente. Las dos declaran las mismas diez regiones con los mismos rótulos, así que
    preferir la nueva no aporta nada y sí cuesta historia: en el cuadro de escolaridad,
    la de 345-22 arranca en 2016 y la de 710-04 en 2000 — dieciséis años que el índice
    necesita para su backfill. La equivalencia geográfica no se asume: si el bloque
    elegido no trae las diez regiones, :func:`parse_schooling` levanta."""
    blocks = [(i, str(r[0])) for i, r in enumerate(rows)
              if r and isinstance(r[0], str) and BLOCK_HEADER in norm(r[0])]
    if not blocks:
        raise SisdomUnavailable(
            f"el cuadro {SHEET} no declara ningún bloque de regiones de desarrollo "
            "(¿cambió el layout del SISDOM?)")

    def _span(idx: int) -> Tuple[int, int]:
        later = [i for i, _t in blocks if i > idx]
        return idx, (later[0] if later else len(rows))

    def _coverage(idx: int) -> int:
        """Observaciones utilizables del bloque: filas que resuelven a región × celdas
        numéricas en columnas de año."""
        start, end = _span(idx)
        from shared.data.one_client import region_slug

        n = 0
        for r in rows[start + 1:end]:
            if not r or not isinstance(r[0], str) or region_slug(r[0]) is None:
                continue
            n += sum(1 for ci in col_year
                     if ci < len(r) and isinstance(r[ci], (int, float)))
        return n

    candidates = [(i, t) for i, t in blocks if any(tag in t for tag in REGIONALIZATIONS)]
    if not candidates:
        raise SisdomUnavailable(
            f"el cuadro {SHEET} declara {len(blocks)} regionalizaciones y ninguna es "
            f"{' ni '.join(REGIONALIZATIONS)}: elegir sería adivinar "
            f"({[t for _i, t in blocks]})")
    best = max(candidates, key=lambda it: (_coverage(it[0]), -it[0]))
    if len(candidates) > 1:
        logger.info("[SISDOM] %s: elegida %r por cobertura (%d observaciones)",
                    SHEET, best[1][:48], _coverage(best[0]))
    return _span(best[0])


def parse_schooling(content: bytes) -> List[Tuple[str, int, float]]:
    """Libro de Educación → ``[(slug, año, años_de_estudio)]`` ordenado.

    Incluye el slug ``pais`` con la fila «Total» del cuadro, que es la cifra nacional y
    NO pertenece a ninguna de las tres regionalizaciones.

    Pura (sin red) para poder fijarla en tests."""
    from shared.data.one_client import REGIONS, region_slug

    rows = open_sheet(content, SHEET)
    col_year = _year_columns(rows)
    if not col_year:
        raise SisdomUnavailable(
            f"no se encontró la fila de años en el cuadro {SHEET}")

    start, end = _select_block(rows, col_year)
    out: List[Tuple[str, int, float]] = []

    # La fila nacional va ANTES de elegir bloque: vive por encima de las tres
    # regionalizaciones y no pertenece a ninguna. Se busca por etiqueta exacta para no
    # confundirla con «Total urbano» o cualquier otro subtotal que el emisor agregue.
    for r in rows[:start]:
        etiqueta = r[0] if r else None
        if not isinstance(etiqueta, str) or etiqueta.strip().casefold() != TOTAL_LABEL:
            continue
        for ci, year in col_year.items():
            v = r[ci] if ci < len(r) else None
            if isinstance(v, (int, float)) and 0 < float(v) <= _MAX_YEARS:
                out.append((COUNTRY_SLUG, year, round(float(v), 2)))
        break

    seen: set = set()
    for r in rows[start + 1:end]:
        label = r[0] if r else None
        slug = region_slug(label) if isinstance(label, str) else None
        if slug is None or slug in seen:
            continue
        seen.add(slug)
        for ci, year in col_year.items():
            v = r[ci] if ci < len(r) else None
            if isinstance(v, (int, float)) and 0 < float(v) <= _MAX_YEARS:
                out.append((slug, year, round(float(v), 2)))

    expected = len({slug for slug, _label in REGIONS})
    if len(seen) != expected:
        raise SisdomUnavailable(
            f"el bloque regional del cuadro {SHEET} trajo {len(seen)} de {expected} "
            f"regiones ({sorted(seen)}): un panel incompleto corre el min-max del "
            "índice y cambia el score de las demás")
    if not out:
        raise SisdomUnavailable(
            f"el cuadro {SHEET} no devolvió ninguna observación utilizable")
    return sorted(out, key=lambda t: (t[1], t[0]))


def fetch_sisdom_schooling() -> List[Tuple[str, int, float]]:  # pragma: no cover - network I/O
    """Live: descubre el libro de Educación en el listado del SISDOM y lo parsea."""
    return parse_schooling(fetch_book(BOOK_FRAGMENT))
