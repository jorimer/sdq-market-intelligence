"""SISDOM (VAES/MEPyD) — ingreso per cápita POR REGIÓN de desarrollo.

Cuadro ``03 3 021`` del libro *Pobreza y Distribución de Ingresos*: «Ingreso familiar
mensual oficial por persona en pesos corrientes», anual 2000-2024, abierto por las 10
regiones de desarrollo (Ley 345-22).

Por qué esta fuente y no la que había
-------------------------------------
La variable ``income_per_capita`` del IDM se llenaba con el *ingreso laboral promedio por
hora* de la ONE: un PROXY declarado, nacional (la misma cifra para las 10 regiones) y —
desde que el portal quedó tras Cloudflare— inalcanzable. Este cuadro la reemplaza por la
variable **exacta**, **regional** y **viva**. Deja de ser una constante con etiqueta
geográfica y pasa a distinguir demarcaciones: en 2024 va de RD$13.428 en El Valle a
RD$19.607 en Cibao Norte.

El mismo libro de mercado de trabajo trae el proxy horario anterior (``06 3 050``, título
idéntico al archivo de la ONE) por si alguna vez hiciera falta continuidad exacta con la
serie vieja; no se conecta porque sería elegir el proxy teniendo la variable.

Dos cuidados que el parser sí toma
----------------------------------
* **Las columnas se ubican resolviendo sus rótulos contra el padrón de regiones**
  (:func:`shared.data.one_client.region_slug`), no por posición. El cuadro pone antes el
  Nacional y la Zona de residencia, y un bloque nuevo correría todo. Si no aparecen las
  10, falla con motivo en vez de entregar un panel incompleto — que el IDM normaliza por
  min-max entre regiones y con menos regiones daría otro score.
* **2016 sale DOS VECES**: ``2016`` (ENFT) y ``2016*`` (ENCFT). El asterisco es la marca
  del propio emisor para la metodología vigente desde 2016; 2017-2024 solo existen
  asteriscados. Quedarse con la fila sin asterisco fabricaría un salto de nivel contra
  2017 que nadie podría explicar después. Se prefiere la asteriscada, explícitamente.

La cifra es **nominal** (pesos corrientes): comparable ENTRE regiones dentro de un año,
que es como la usa el IDM, no deflactada a lo largo del tiempo.
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

logger = logging.getLogger("sdq.data.sisdom")

# El cuadro trae una columna ``Nacional`` —el propio docstring lo dice— y el parser la deja
# fuera porque no resuelve contra el padrón de regiones. Se declara en vez de capturarla:
# el único indicador de la END que la usaría es el 3.26, y ese está DESCARTADO por otra
# razón (el ingreso familiar mensual del hogar no es el INB per cápita anual por método
# Atlas). Capturar una serie que ningún consumidor pide sería trabajo muerto; perderla sin
# decirlo es lo que ya costó dos veces.
SIN_TOTAL_NACIONAL = (
    "la columna `Nacional` existe y se descarta a propósito: el indicador 3.26 de la END, "
    "único consumidor posible, está descartado porque mide otra magnitud (INB per cápita "
    "anual por método Atlas, no ingreso familiar mensual del hogar)."
)


UNIT = "RD$/mes por persona (corrientes)"   # ≤40: sd_indicators.unit es VARCHAR(40)

# Fragmento del título del libro en el listado, insensible a acentos. El listado rotula
# la EDICIÓN ("SISDOM 2024 – …"), así que se matchea el tema y se elige la edición más
# nueva; clavar el id sería atarse a la edición de hoy.
BOOK_FRAGMENT = "pobreza y distribucion de ingresos"
SHEET = "03 3 021"          # el libro escribe el nombre con espacio final
INDICATOR = "Ingreso familiar mensual oficial por persona en pesos corrientes"

_YEAR = re.compile(r"^((?:19|20)\d{2})")
_ANNUAL_ROW = "ano"          # la fila "Año" (vs. "Marzo"/"Septiembre")
_HEADER_SCAN_ROWS = 15
_MAX_REASONABLE = 10_000_000.0   # RD$/mes por persona: un valor mayor es basura de celda

# Regionalizaciones que el SISDOM usa en sus cuadros, de la vigente a la anterior. Las dos
# traen las MISMAS 10 regiones de desarrollo. La tercera —Dec 685-00— usa otro conjunto
# ("Distrito Nacional" como región propia), así que sus etiquetas resuelven a medias y sus
# cifras NO son comparables. Hoy este cuadro trae solo la 345-22, pero cuadros hermanos del
# mismo sistema traen las tres apiladas: si una edición futura las agrega acá, elegir "el
# bloque cuyas etiquetas resuelvan" agarraría la vieja y entregaría otra regionalización sin
# que nada lo advirtiera. Por eso el bloque se elige por lo que el emisor DECLARA.
REGIONALIZATIONS = ("345-22", "710-04")
BLOCK_HEADER = "regiones de desarrollo"


def parse_income_per_capita(content: bytes) -> List[Tuple[str, int, float]]:
    """Libro de Pobreza/Ingresos → ``[(region_slug, año, RD$/mes por persona)]``.

    Pura (sin red) para poder fijarla en tests. Ver el encabezado del módulo por las dos
    trampas del cuadro: las columnas se ubican por rótulo y el 2016 duplicado se resuelve
    por el asterisco del emisor."""
    from shared.data.one_client import region_slug

    rows = open_sheet(content, SHEET)

    # 1) fila de encabezado = la que resuelve MÁS rótulos contra el padrón de regiones.
    #    'Nacional', 'Urbana' y 'Rural' no resuelven, así que quedan fuera solas.
    header_row = -1
    col_slug: Dict[int, str] = {}
    for i, r in enumerate(rows[:_HEADER_SCAN_ROWS]):
        found: Dict[int, str] = {}
        for ci, cell in enumerate(r):
            slug = region_slug(cell) if isinstance(cell, str) else None
            if slug is not None:
                found[ci] = slug
        if len(found) > len(col_slug):
            header_row, col_slug = i, found
    col_slug = _restrict_to_declared_block(rows[:_HEADER_SCAN_ROWS], col_slug)
    expected = len(_region_slugs())
    if len(col_slug) != expected:
        raise SisdomUnavailable(
            f"se ubicaron {len(col_slug)} de {expected} regiones en el encabezado del "
            f"cuadro {SHEET} (¿cambió el layout del SISDOM?)")

    # 2) filas anuales. La etiqueta de año aparece solo en la PRIMERA fila de su grupo
    #    (Marzo/Septiembre/Año), así que se arrastra.
    by_year: Dict[int, Tuple[bool, List[Tuple[str, int, float]]]] = {}
    year: Optional[int] = None
    starred = False
    for r in rows[header_row + 1:]:
        if not r:
            continue
        label = str(r[0]).strip() if r[0] is not None else ""
        m = _YEAR.match(label)
        if m:
            year, starred = int(m.group(1)), "*" in label
        if year is None or len(r) < 2 or norm(r[1]) != _ANNUAL_ROW:
            continue
        obs = [(slug, year, round(float(r[ci]), 2))
               for ci, slug in col_slug.items()
               if ci < len(r) and isinstance(r[ci], (int, float))
               and 0 < float(r[ci]) < _MAX_REASONABLE]
        prev = by_year.get(year)
        if prev is None or (starred and not prev[0]):
            # Sin duplicado, o la asteriscada desplaza a la vieja: ver módulo (2016).
            by_year[year] = (starred, obs)
        elif starred == prev[0]:
            raise SisdomUnavailable(
                f"el año {year} aparece dos veces con la misma marca de metodología en "
                f"el cuadro {SHEET}: no hay forma de elegir sin adivinar")

    out = [o for _starred, obs in by_year.values() for o in obs]
    if not out:
        raise SisdomUnavailable(
            f"el cuadro {SHEET} no devolvió ninguna observación anual utilizable")
    return sorted(out, key=lambda t: (t[1], t[0]))


def _restrict_to_declared_block(head: List[list], col_slug: Dict[int, str]) -> Dict[int, str]:
    """Deja solo las columnas del bloque de regionalización VIGENTE que declara el cuadro.

    Los bloques se anuncian en una fila propia ("Regiones de Desarrollo (Ley 345-22)") sobre
    la primera de sus columnas, y se extienden hasta el anuncio siguiente. Si el cuadro no
    declara ninguno —ediciones viejas, o una hoja con una sola regionalización sin rótulo—
    no hay nada que desambiguar y se devuelve lo que había: este guard descarta, nunca
    inventa."""
    blocks: List[Tuple[int, str]] = []       # (columna de inicio, texto declarado)
    for r in head:
        for ci, cell in enumerate(r):
            if isinstance(cell, str) and BLOCK_HEADER in norm(cell):
                blocks.append((ci, cell))
    if len(blocks) < 2:
        return col_slug

    starts = sorted(ci for ci, _t in blocks)
    chosen = next((ci for tag in REGIONALIZATIONS
                   for ci, text in sorted(blocks) if tag in text), None)
    if chosen is None:
        raise SisdomUnavailable(
            f"el cuadro {SHEET} declara {len(blocks)} regionalizaciones y ninguna es "
            f"{' ni '.join(REGIONALIZATIONS)}: elegir sería adivinar "
            f"({[t for _c, t in blocks]})")
    later = [s for s in starts if s > chosen]
    end = later[0] if later else max(col_slug, default=chosen) + 1
    return {ci: slug for ci, slug in col_slug.items() if chosen <= ci < end}


def _region_slugs() -> set:
    from shared.data.one_client import REGIONS

    return {slug for slug, _label in REGIONS}


def fetch_sisdom_income_per_capita() -> List[Tuple[str, int, float]]:  # pragma: no cover - network I/O
    """Live: descubre el libro de Pobreza/Ingresos en la edición vigente y lo parsea.

    El descubrimiento y la descarga viven en :mod:`shared.data.sisdom_common`. Este módulo
    tenía su propia copia y por eso se quedó apuntando a ``mepyd.gob.do`` cuando el emisor
    se mudó a Hacienda: el arreglo se hizo una sola vez, del otro lado.
    """
    return parse_income_per_capita(fetch_book(BOOK_FRAGMENT))
