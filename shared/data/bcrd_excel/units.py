"""Capturar la UNIDAD que el emisor declara en la planilla — no adivinarla después.

El BCRD SIEMPRE dice en qué mide cada cuadro, en una fila de *caption* sobre los datos o
entre paréntesis en el rótulo de cada columna:

* ``bpagos``            → ``(En Millones de US$)``            (unidad de hoja, flujo)
* ``agregados_monet.``  → ``Saldos en millones de:``         (unidad de hoja, stock)
* ``taap_activad``      → ``PROMEDIO PONDERADO EN % NOMINAL`` (unidad de hoja, tasa)
* ``pib_deflactor``     → ``PIB nominal (Millones de RD$)`` · ``Variación interanual (%)``
                          (unidad POR COLUMNA — dos magnitudes distintas en la misma hoja)

La extracción venía tirando ese texto y poniendo ``unit=None`` en todos los registros. Sin
la unidad, la naturaleza de la serie queda ``unknown`` y el motor no puede leer su momentum
— 216 series del BCRD caían ahí. Este módulo la RECUPERA de la fuente, de forma
determinística; el mapeo unidad→naturaleza lo hace :func:`shared.data.series_nature`.

No se inventa: si la planilla no declara unidad, se devuelve ``None`` y la serie queda en
``unknown`` honesto.
"""
from __future__ import annotations

import re
from typing import Any, Optional, Tuple

# Un caption de unidad: dinero (con o sin "saldos"), porcentaje, o índice. Se conserva el
# texto completo del caption —incluida la palabra "Saldos"— porque distingue un STOCK de un
# flujo, y eso lo lee después ``infer_nature``.
_MONEY = r"millones\s+de\s+(?:us\$|rd\$|d[óo]lares|pesos|euros)|(?:saldos?\s+)?en\s+millones|millones\s+de\s+pesos"
# Solo captions con el TOKEN "%": un título como "Tasas de Interés Nominales" describe la
# hoja pero no es la unidad — la unidad es el "% nominal anual" que el BCRD pone aparte.
_PCT = r"promedio\s+ponderado\s+en\s+%|en\s+%(?:\s+nominal)?|\(\s*%\s*\)|por\s+ciento"
_INDEX = r"[íi]ndice(?:\s+de\s+volumen)?"
_UNIT_CAPTION = re.compile(rf"({_MONEY}|{_PCT}|{_INDEX})", re.IGNORECASE)

# Unidad entre paréntesis al final de un rótulo de columna: "PIB nominal (Millones de RD$)".
_PAREN_UNIT = re.compile(
    r"\(\s*((?:millones\s+de\s+)?(?:us\$|rd\$|d[óo]lares|pesos)|%|[íi]ndice[^)]*|"
    r"millones[^)]*|var[^)]*%[^)]*)\s*\)", re.IGNORECASE)


def _text(v: Any) -> str:
    return str(v).strip() if v is not None and not isinstance(v, (int, float)) else ""


def normalize_unit(raw: Optional[str]) -> Optional[str]:
    """Reducir un caption a una unidad CORTA y canónica que quepa y se lea igual.

    El objetivo de capturar la unidad es (a) clasificar la naturaleza de la serie y (b)
    mostrársela al cliente — no archivar el título entero del cuadro. Un caption como
    "Índices de volumen encadenados, referenciados al año 2018" (57 car.) no es una unidad:
    la unidad es "Índice". Además la columna es ``VARCHAR(40)``; sin esto, esos títulos
    largos reventaban la persistencia. Se preserva la señal de "Saldos" (distingue un stock)
    y la moneda cuando el emisor la declara."""
    if not raw:
        return None
    low = raw.lower()
    if re.search(r"%|por\s+ciento", low):
        return "%"
    if re.search(r"[íi]ndice", low):
        return "Índice"
    if re.search(r"millones|mm\s*us\$|us\$|rd\$|d[óo]lar|pesos|euros", low):
        saldo = "Saldos, " if "saldo" in low else ""
        if re.search(r"us\$|d[óo]lar", low):
            moneda = "millones de US$"
        elif "rd$" in low or "pesos" in low:
            moneda = "millones de RD$"
        else:
            moneda = "millones"
        out = f"{saldo}{moneda}"
        return (out[:1].upper() + out[1:])[:40]
    return raw.strip()[:40]


def sheet_unit(grid: Any, upper_bound: Optional[int]) -> Optional[str]:
    """Unidad declarada en la ZONA DE TÍTULO de la hoja (filas sobre el encabezado).

    ``upper_bound`` es la primera fila que YA es encabezado/datos (p.ej. la fila de años en
    un ``matrix``): se escanea solo por encima para no confundir un caption de hoja con el
    rótulo de una columna (una hoja mixta como llegadas tiene "Tasa de Crecimiento (%)" en
    el encabezado, y NO es la unidad de toda la hoja). Se devuelve el texto del caption tal
    cual —limpio de paréntesis envolventes— para que ``infer_nature`` lo interprete."""
    top = upper_bound if upper_bound is not None else 0
    top = min(top, grid.nrows)
    best: Optional[str] = None
    for r in range(top):
        for c in range(min(grid.ncols, 8)):
            txt = _text(grid.cell(r, c))
            if not txt or len(txt) > 80:
                continue
            if _UNIT_CAPTION.search(txt):
                # El primer caption de la zona de título gana; suele ser el más general.
                if best is None:
                    best = txt
    return normalize_unit(best)


def split_header_unit(name: str) -> Tuple[str, Optional[str]]:
    """Separar ``"PIB nominal (Millones de RD$)"`` → ``("PIB nominal", "Millones de RD$")``.

    Cuando una hoja publica varias magnitudes en columnas contiguas, la unidad viaja entre
    paréntesis en el rótulo. Se extrae para que cada serie lleve la suya; el nombre pierde
    el paréntesis de unidad (no el resto de su texto). Sin paréntesis de unidad, la unidad
    es ``None`` y el nombre queda intacto."""
    if not name:
        return name, None
    m = _PAREN_UNIT.search(name)
    if not m:
        return name, None
    unit = normalize_unit(m.group(1).strip())
    cleaned = (name[:m.start()] + name[m.end():]).strip().rstrip("·").strip()
    return (cleaned or name), unit
