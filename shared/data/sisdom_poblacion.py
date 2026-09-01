"""SISDOM — POBLACIÓN por región de desarrollo (proyecciones ONE).

Cuadro ``02 3 009b`` del libro de *Indicadores Demográficos*: la población de las 10
regiones de desarrollo, anual, según las proyecciones de la ONE.

Para qué se conecta, que no es lo obvio
---------------------------------------
No alimenta el IDM. Es la variable de **TAMAÑO** del eje social: el control que responde
«¿el IDM ordena el desarrollo regional, o solo ordena por cuán grande es la región?».
Hasta hoy `social_dev` era el ÚNICO motor del catálogo sin control por tamaño, y el motivo
declarado era de DATO —la población por región no estaba conectada—, no de diseño.

Por qué la hoja de PROYECCIONES y no la de encuesta
---------------------------------------------------
El mismo libro trae ``02 3 009a``, la población por región según las encuestas (ENFT/ENCFT).
Se elige ``009b`` a propósito: la de encuesta es un ESTIMADOR con error muestral y se mueve
de forma no demográfica —Valdesia va de 868 mil a 818 mil y vuelve a 874 mil entre 2019 y
2022, y El Valle salta 45 mil en un año—, mientras que un denominador poblacional para
controlar tamaño tiene que ser una magnitud estructural. Ordenar regiones por una serie que
se sacude con la muestra mide ruido, no tamaño.

La contrapartida se declara: son proyecciones basadas en el censo de **2010** (revisión ONE
2014), no en el **Censo 2022**. Para lo que se usa —el ORDEN de tamaño entre regiones, que
es estable— eso no cambia el veredicto; para citar una población en un informe, sí
importaría, y por eso viaja el nombre de la fuente.
"""
from __future__ import annotations

import logging
import re
from typing import Dict, List, Tuple

from shared.data.sisdom_common import (
    LICENSE,
    SOURCE,
    SisdomUnavailable,
    fetch_book,
    norm,
    open_sheet,
)

logger = logging.getLogger("sdq.data.sisdom_poblacion")

__all__ = ["LICENSE", "SOURCE", "THEME", "UNIT", "SisdomUnavailable",
           "fetch_poblacion_regional", "parse_poblacion"]

BOOK_FRAGMENT = "indicadores demograficos"
SHEET = "02 3 009b"
THEME = "population"
UNIT = "habitantes (proyección ONE)"          # ≤40: sd_indicators.unit es VARCHAR(40)
LABEL = "Población de la región (proyecciones ONE)"

#: La fila ``Total`` existe y se descarta sola: no resuelve contra el padrón de regiones.
#: Se declara igual —la regla del repo es DECIDIR qué se hace con el total país— porque acá
#: no hace falta: el control compara regiones ENTRE sí y un total no es una de ellas.
SIN_TOTAL_NACIONAL = (
    "la fila `Total` existe y se descarta a propósito: este dato solo se usa para ordenar "
    "regiones entre sí (control por tamaño), y el total del país no es una región."
)

_YEAR_CELL = re.compile(r"^((?:19|20)\d{2})")
_HEADER_SCAN_ROWS = 12
#: Población de una región dominicana: fuera de este rango es basura de celda, no un dato.
_MIN_HAB, _MAX_HAB = 10_000.0, 20_000_000.0


def _year_columns(rows: List[list]) -> Dict[int, int]:
    """``{columna: año}`` de la fila de encabezado — la que trae más años."""
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


def parse_poblacion(content: bytes) -> List[Tuple[str, int, float]]:
    """Libro Demográfico → ``[(region_slug, año, habitantes)]``. Pura (sin red).

    A diferencia del cuadro de ingreso, acá las regiones son FILAS y los años COLUMNAS. Se
    ubican resolviendo el rótulo de cada fila contra el padrón de regiones, nunca por
    posición: un bloque nuevo arriba correría todo.
    """
    from shared.data.one_client import REGIONS, region_slug

    rows = open_sheet(content, SHEET)
    años = _year_columns(rows)
    if not años:
        raise SisdomUnavailable(
            f"el cuadro {SHEET} no trae una fila de años reconocible (¿cambió el layout?)")

    out: List[Tuple[str, int, float]] = []
    vistas: set = set()
    for r in rows:
        etiqueta = r[0] if r else None
        slug = region_slug(etiqueta) if isinstance(etiqueta, str) else None
        if slug is None:
            continue
        vistas.add(slug)
        for ci, anio in años.items():
            if ci >= len(r) or not isinstance(r[ci], (int, float)):
                continue
            valor = float(r[ci])
            if _MIN_HAB < valor < _MAX_HAB:
                out.append((slug, anio, round(valor, 1)))

    # Las 10, o ninguna. Un control de tamaño computado sobre 8 regiones se compararía
    # contra un score de 10 y las dos cifras hablarían de universos distintos — que es
    # exactamente lo que `COBERTURA_MINIMA` veta después, pero acá se ve la causa.
    esperadas = {slug for slug, _label in REGIONS}
    if vistas != esperadas:
        raise SisdomUnavailable(
            f"el cuadro {SHEET} resolvió {len(vistas)} de {len(esperadas)} regiones "
            f"(faltan: {sorted(esperadas - vistas)}): un panel incompleto no controla nada")
    if not out:
        raise SisdomUnavailable(
            f"el cuadro {SHEET} no devolvió ninguna población utilizable")
    return sorted(out, key=lambda t: (t[1], t[0]))


def fetch_poblacion_regional() -> List[Tuple[str, int, float]]:  # pragma: no cover - network I/O
    """Live: descubre el libro Demográfico de la edición vigente y lo parsea."""
    return parse_poblacion(fetch_book(BOOK_FRAGMENT))
