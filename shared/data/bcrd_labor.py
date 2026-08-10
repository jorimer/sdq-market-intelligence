"""ENCFT del Banco Central — informalidad laboral desde la FUENTE PRIMARIA.

Sustituye el raspado de la landing de la ONE, que dejó de funcionar cuando el portal
quedó detrás de un desafío de Cloudflare (403 desde cualquier cliente que no sea un
navegador, también desde producción). La reacción intuitiva sería pelear con el
desafío; la correcta era preguntarse **quién produce el dato**. La ONE no lo produce:
lo republica. La ENCFT es del BCRD, que publica sus tablas en el mismo CDN público del
que este repo ya baja otras series —sin token, sin navegador y sin User-Agent fingido.

El cambio deja el dato MEJOR de lo que estaba:

* fuente primaria en vez de republicación (un intermediario menos);
* cobertura 2014-2026 en vez de 2004-2024;
* la tasa viene **publicada por el emisor**, no calculada por nosotros.

Se toman las ventanas de AÑO CALENDARIO (``I YYYY - IV YYYY``) de la hoja de promedios
móviles: son las únicas comparables con una serie anual. Usar una ventana móvil
cualquiera y estamparla con un año sería inventar una correspondencia.

Nota de alcance: acá SOLO viaja la informalidad. El BCRD publica los deciles de ingreso
como CONTEOS de perceptores, no como montos, así que el ingreso laboral promedio —que
la ONE sí calculaba— no tiene sustituto en esta fuente. Declararlo es preferible a
rellenarlo con algo parecido.
"""
from __future__ import annotations

import io
import logging
import re
import unicodedata
from typing import List, Optional, Tuple

logger = logging.getLogger("sdq.data.bcrd_labor")

CDN = ("https://cdn.bancentral.gov.do/documents/estadisticas/"
       "mercado-de-trabajo/documents/")
INDICATORS_FILE = "00_Indicadores.xlsx"
INDICATORS_URL = CDN + INDICATORS_FILE

SOURCE = "BCRD"
LICENSE = "estadísticas públicas del Banco Central de la República Dominicana — uso con cita"
SHEET = "Promedio 4 Trimestres"

# Fila del indicador. "Ocupación Informal" es la informalidad DEL EMPLEO (la que la ONE
# republicaba como «tasa de informalidad en el empleo»); "Sector Informal" mide otra cosa
# —el peso del sector— y corre ~6 puntos más abajo. Confundirlas cambiaría el nivel de la
# serie sin que nada lo advirtiera, así que la etiqueta se exige explícita.
INFORMALITY_LABEL = "ocupacion informal"

# Ventana de año calendario: "I 2015 - IV 2015". El resto son móviles y no son anuales.
_CALENDAR_WINDOW = re.compile(r"^\s*I\s+((?:19|20)\d{2})\s*-\s*IV\s+((?:19|20)\d{2})\s*$")
_HEADER_SCAN_ROWS = 12


class BcrdLaborUnavailable(RuntimeError):
    """No se pudo leer la serie. Lleva el motivo, no solo el hecho."""


def _norm(s: object) -> str:
    if s is None:
        return ""
    t = unicodedata.normalize("NFKD", str(s))
    t = "".join(c for c in t if not unicodedata.combining(c))
    return " ".join(t.casefold().split())


def parse_informality(content: bytes,
                      label: str = INFORMALITY_LABEL) -> List[Tuple[int, float]]:
    """Parsea ``00_Indicadores.xlsx`` → ``[(año, tasa_de_informalidad)]`` ascendente.

    Localiza la columna por el ENCABEZADO de ventana (no por posición) y la fila por su
    etiqueta, igual que el resto de los parsers de planilla del repo: así un cambio de
    layout deja la serie vacía —visible— en vez de leer la fila equivocada en silencio.
    Pura (sin red), para poder fijarla en tests."""
    import openpyxl

    wb = openpyxl.load_workbook(io.BytesIO(content), data_only=True, read_only=True)
    try:
        if SHEET not in wb.sheetnames:
            raise BcrdLaborUnavailable(
                f"el libro no trae la hoja '{SHEET}' (hojas: {wb.sheetnames})")
        rows = [list(r) for r in wb[SHEET].iter_rows(values_only=True)]
    finally:
        wb.close()

    # 1) columnas de año calendario, desde la fila de encabezado.
    year_by_col: dict = {}
    for r in rows[:_HEADER_SCAN_ROWS]:
        for ci, cell in enumerate(r):
            m = _CALENDAR_WINDOW.match(cell) if isinstance(cell, str) else None
            if m and m.group(1) == m.group(2):
                year_by_col[ci] = int(m.group(1))
        if year_by_col:
            break
    if not year_by_col:
        raise BcrdLaborUnavailable(
            "no se encontró ninguna ventana de año calendario ('I YYYY - IV YYYY') "
            "en el encabezado (¿cambió el layout del BCRD?)")

    # 2) la fila del indicador, por etiqueta exacta normalizada.
    target = _norm(label)
    data_row: Optional[list] = None
    for r in rows:
        if r and _norm(r[0]) == target:
            data_row = r
            break
    if data_row is None:
        raise BcrdLaborUnavailable(
            f"no se encontró la fila '{label}' en la hoja '{SHEET}'")

    out: List[Tuple[int, float]] = []
    for ci, year in sorted(year_by_col.items(), key=lambda kv: kv[1]):
        v = data_row[ci] if ci < len(data_row) else None
        if isinstance(v, (int, float)) and 0 < float(v) <= 100:
            out.append((year, round(float(v), 2)))
    if not out:
        raise BcrdLaborUnavailable(
            f"la fila '{label}' no trae ningún valor en rango 0-100")
    return out


def fetch_bcrd_informality() -> List[Tuple[int, float]]:  # pragma: no cover - network I/O
    """Live: descarga el libro de indicadores del CDN del BCRD y lo parsea."""
    import httpx

    try:
        r = httpx.get(INDICATORS_URL, timeout=120, follow_redirects=True)
        r.raise_for_status()
    except httpx.HTTPError as e:
        raise BcrdLaborUnavailable(
            f"no se pudo descargar {INDICATORS_FILE} del CDN del BCRD "
            f"({type(e).__name__}: {e})")
    return parse_informality(r.content)
