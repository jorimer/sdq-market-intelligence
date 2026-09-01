"""SISDOM (MEPyD) — mortalidad infantil POR PROVINCIA (rondas ENDESA 2002 y 2007).

Cuadro ``04 3 035b`` del libro de Salud, bloque ``Provincia``: las 32 con dato.

**Esta serie NO alimenta el IDM, y la distinción importa.** El índice usa la serie anual
viva de WDI (nacional, hasta 2024). Cambiarla por esto ganaría apertura territorial y
perdería vigencia: son dos cortes de encuesta, el último de 2007, así que todo período
posterior quedaría con el mismo número congelado — otra constante nacional, solo que con
etiqueta provincial y desactualizada. Es el intercambio INVERSO al del ingreso y la
escolaridad, donde se ganó apertura Y serie hasta 2024.

Se publica como serie propia porque **sí es dato oficial y sí discrimina entre
demarcaciones**: sirve para caracterizar estructuralmente una provincia, no para ordenar
demarcaciones hoy. El período viaja en cada observación, así que quien la consuma ve por
sí mismo que está leyendo 2002 o 2007.

El código de tema lleva el nombre de la encuesta (``endesa_child_mortality``) y no
``child_mortality``: comparten concepto pero no metodología —una es estimación modelada
anual del Banco Mundial y la otra una encuesta de hogares— y darles el mismo código
invitaría a graficarlas juntas.
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

logger = logging.getLogger("sdq.data.sisdom_child_mortality")

# El cuadro trae una fila ``Nacional`` (79,2 en 1975 …) y el parser la deja fuera al filtrar
# por provincia. Se declara en vez de capturarla por dos motivos que se suman: la serie del
# ENDESA termina en 2013 —no sirve para juzgar una meta de 2025— y el único indicador de la
# END sobre mortalidad de menores es el 2.22, que mide menores de 5 AÑOS mientras esta es
# INFANTIL (menores de 1). Ninguna transformación las convierte.
#: LA HOJA SE RETIRÓ, y no se sustituye. Verificado el 2026-09-01 contra la edición 2025 del
#: libro de Salud (la primera que publica Hacienda tras absorber al MEPyD): el cuadro
#: ``04 3 035b`` ya no está. Lo que sí está son ``04 3 035a`` —tasa ESTIMADA, registros del
#: SINAVE— y ``04 3 035d`` —tasa PROYECTADA, proyecciones de población—, y ninguna de las dos
#: es la ronda ENDESA: son un registro administrativo y una proyección demográfica. Tomarlas
#: publicaría otra magnitud bajo la etiqueta «(ENDESA)», que es exactamente el defecto que la
#: hoja DECLARADA existe para impedir en este repo.
#:
#: Lo ya persistido (2002 y 2007 por provincia) no se toca: `_upsert_indicator` nunca purga.
#: Lo que se perdió es la relectura, y el conector lo dice en vez de degradar a «sin dato».
HOJA_RETIRADA = (
    "la edición vigente del libro de Salud ya no trae el cuadro {hoja} (rondas ENDESA por "
    "provincia). Trae «04 3 035a» (estimada, registros SINAVE) y «04 3 035d» (proyectada), "
    "que miden otra cosa: no se sustituyen. Lo ya ingerido de 2002 y 2007 sigue en la base"
)

SIN_TOTAL_NACIONAL = (
    "la fila `Nacional` existe y se descarta a propósito: la serie ENDESA termina en 2013 "
    "y mide mortalidad INFANTIL (menores de 1 año), no la de menores de 5 del indicador "
    "2.22 de la END."
)


__all__ = ["LICENSE", "SOURCE", "THEME", "UNIT", "SisdomUnavailable",
           "fetch_endesa_child_mortality", "parse_child_mortality"]

BOOK_FRAGMENT = "indicadores de salud"
SHEET = "04 3 035b"
THEME = "endesa_child_mortality"
UNIT = "por 1.000 nacidos vivos (ENDESA)"     # ≤40: sd_indicators.unit es VARCHAR(40)
LABEL = "Mortalidad infantil (ENDESA)"

_BLOCK = "provincia"          # el rótulo que abre el bloque provincial
_YEAR_CELL = re.compile(r"^((?:19|20)\d{2})")
_HEADER_SCAN_ROWS = 12
# Tasa por mil nacidos vivos: por encima de 200 es un artefacto de celda, no un dato.
_MAX_RATE = 200.0


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


def parse_child_mortality(content: bytes) -> List[Tuple[str, int, float]]:
    """Libro de Salud → ``[(province_slug, año, tasa)]`` ordenado.

    El bloque provincial se abre con una fila cuyo único contenido es ``Provincia`` y
    corre hasta que una etiqueta deja de resolver contra el padrón. Las celdas sin dato
    llegan como ``'. . .'`` —el emisor marca así lo no disponible— y se descartan solas
    al no ser numéricas. Pura (sin red) para poder fijarla en tests."""
    from shared.reference.provinces import province_slug

    rows = open_sheet(content, SHEET)
    col_year = _year_columns(rows)
    if not col_year:
        raise SisdomUnavailable(f"no se encontró la fila de años en el cuadro {SHEET}")

    start = next((i for i, r in enumerate(rows)
                  if r and isinstance(r[0], str) and norm(r[0]) == _BLOCK), None)
    if start is None:
        raise SisdomUnavailable(
            f"el cuadro {SHEET} no declara el bloque '{_BLOCK}' (¿cambió el layout?)")

    out: List[Tuple[str, int, float]] = []
    seen: set = set()
    for r in rows[start + 1:]:
        slug = province_slug(r[0]) if r and isinstance(r[0], str) else None
        if slug is None:
            if seen:
                break              # terminó el bloque provincial
            continue
        seen.add(slug)
        for ci, year in col_year.items():
            v = r[ci] if ci < len(r) else None
            if isinstance(v, (int, float)) and 0 < float(v) <= _MAX_RATE:
                out.append((slug, year, round(float(v), 2)))

    if not out:
        raise SisdomUnavailable(
            f"el bloque provincial del cuadro {SHEET} no trajo ninguna observación")
    faltan = 32 - len(seen)
    if faltan:
        # Nota, no error: a diferencia del IDM, esta serie no se normaliza contra un
        # panel, así que una provincia ausente es un hueco honesto y no distorsiona nada.
        logger.info("[SISDOM] %s: %d provincias sin fila en el bloque", SHEET, faltan)
    return sorted(out, key=lambda t: (t[1], t[0]))


def fetch_endesa_child_mortality() -> List[Tuple[str, int, float]]:  # pragma: no cover - network I/O
    """Live: descubre el libro de Salud de la edición vigente y lo parsea.

    Si la hoja no está, el error lleva el MOTIVO —no solo el hecho—: hoy no está porque el
    emisor la retiró, y las candidatas que quedan miden otra cosa. Sin eso, el mensaje
    «el libro no trae la hoja» se lee como un cambio de nombre que alguien va a "arreglar"
    apuntando a la hoja de al lado.
    """
    contenido = fetch_book(BOOK_FRAGMENT)
    try:
        return parse_child_mortality(contenido)
    except SisdomUnavailable as e:
        if "no trae la hoja" in str(e):
            raise SisdomUnavailable(HOJA_RETIRADA.format(hoja=SHEET)) from e
        raise
