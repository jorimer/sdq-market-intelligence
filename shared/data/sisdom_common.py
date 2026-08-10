"""SISDOM (VAES/MEPyD) — descubrimiento y descarga, común a todos sus libros.

El SISDOM publica un libro Excel por área temática y de ahí salen ya dos variables del
IDM: el ingreso per cápita (*Pobreza y Distribución de Ingresos*) y la escolaridad
promedio (*Educación*). Descubrir el libro y bajarlo es idéntico en los dos casos; lo
único que cambia es el layout de la hoja. Esta plumbing vive acá para que no haya dos
copias que envejezcan por separado — que es exactamente cómo se rompe un conector
cuando el emisor cambia algo y solo se arregla una de las dos.

Los ``file_id`` **se descubren del listado**, nunca se clavan: rotan con cada edición
anual, y clavarlos repetiría el error del raspado de la ONE, que se rompió el día que
cambió la página.
"""
from __future__ import annotations

import io
import re
import unicodedata
from html import unescape
from typing import Optional, Tuple

LISTING_URL = "https://mepyd.gob.do/sisdom/areas-tematicas"
DOWNLOAD_URL = "https://mepyd.gob.do/wp-admin/admin-ajax.php"

SOURCE = "MEPyD"
LICENSE = "SISDOM (VAES/MEPyD) — indicadores sociales oficiales, uso público con cita"

HEADERS = {"User-Agent": "Mozilla/5.0 (SDQ-MIP SISDOM connector)"}

# Regionalizaciones, en orden de preferencia. La de 685-00 queda FUERA a propósito: usa
# otro conjunto de regiones, y mezclarla produciría una serie incoherente en silencio.
REGIONALIZATIONS = ("345-22", "710-04")
BLOCK_HEADER = "regiones de desarrollo"

_WPFD_ANCHOR = re.compile(r'<a\b([^>]*wpfd-file-link[^>]*)>(.*?)</a>', re.S | re.I)
_ATTR = {"file": re.compile(r'data-id="(\d+)"'),
         "category": re.compile(r'data-category_id="(\d+)"')}
_TAGS = re.compile(r"<[^>]+>")


class SisdomUnavailable(RuntimeError):
    """El listado o un libro del SISDOM no se pudo leer. Lleva el motivo."""


def norm(s: object) -> str:
    """Clave insensible a acento/caso/espacios para calzar títulos y rótulos."""
    if s is None:
        return ""
    t = unicodedata.normalize("NFKD", str(s))
    t = "".join(c for c in t if not unicodedata.combining(c))
    return " ".join(t.casefold().split())


def edition_year(title: str) -> int:
    """Mayor año de 4 dígitos del título ('SISDOM 2024 – …') → 2024, o 0."""
    return max((int(y) for y in re.findall(r"(?:19|20)\d{2}", title)), default=0)


def discover_book(html_text: str, fragment: str) -> Optional[Tuple[str, str]]:
    """``(category_id, file_id)`` del libro cuyo título contiene *fragment*, o ``None``.

    Si hay varias ediciones publicadas gana la de año más alto (desempate determinista).
    El listado incluye una plantilla Handlebars con la misma clase y sin ids: se descarta
    sola al exigir ambos atributos."""
    best: Optional[Tuple[int, str, str]] = None
    for attrs, inner in _WPFD_ANCHOR.findall(html_text):
        fid, cid = _ATTR["file"].search(attrs), _ATTR["category"].search(attrs)
        if not fid or not cid:
            continue
        title = unescape(_TAGS.sub("", inner)).strip()
        if norm(fragment) not in norm(title):
            continue
        year = edition_year(title)
        if best is None or year > best[0]:
            best = (year, cid.group(1), fid.group(1))
    return (best[1], best[2]) if best else None


def fetch_book(fragment: str) -> bytes:  # pragma: no cover - network I/O
    """Descubre el libro por su título, lo baja y devuelve el ``.xlsx`` crudo."""
    import httpx

    try:
        with httpx.Client(timeout=180, follow_redirects=True, headers=HEADERS) as client:
            listing = client.get(LISTING_URL)
            listing.raise_for_status()
            found = discover_book(listing.text, fragment)
            if found is None:
                raise SisdomUnavailable(
                    f"no se encontró el libro '{fragment}' en {LISTING_URL} "
                    "(¿cambió el título o se despublicó la edición?)")
            category_id, file_id = found
            book = client.get(DOWNLOAD_URL, params={
                "juwpfisadmin": "false", "action": "wpfd", "task": "file.download",
                "wpfd_category_id": category_id, "wpfd_file_id": file_id,
            })
            book.raise_for_status()
    except httpx.HTTPError as e:
        raise SisdomUnavailable(
            f"no se pudo bajar el libro del SISDOM ({type(e).__name__}: {e})")
    if not book.content.startswith(b"PK"):
        # El plugin devuelve 200 con HTML cuando el id ya no existe: sin este guard,
        # openpyxl fallaría con un error de zip que no dice nada sobre la causa real.
        raise SisdomUnavailable(
            f"la descarga del libro {file_id} no es un .xlsx "
            f"({len(book.content)} bytes, {book.headers.get('content-type')})")
    return book.content


def open_sheet(content: bytes, sheet: str):
    """Abre la hoja por nombre normalizado — los libros escriben ``'03 3 021 '`` con
    espacio final. Devuelve las filas como listas; cierra el libro siempre."""
    import openpyxl

    wb = openpyxl.load_workbook(io.BytesIO(content), data_only=True, read_only=True)
    try:
        name = next((n for n in wb.sheetnames if norm(n) == norm(sheet)), None)
        if name is None:
            raise SisdomUnavailable(
                f"el libro no trae la hoja '{sheet}' (hojas: {wb.sheetnames[:12]}…)")
        return [list(r) for r in wb[name].iter_rows(values_only=True)]
    finally:
        wb.close()
