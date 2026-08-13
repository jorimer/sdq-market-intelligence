"""Segments engine — the population a figure describes, written one way only.

A tracker prints the same cut three ways across one deck: «SD», «Sto. Domingo» and «Santo
Domingo» are one population, and stored verbatim they become three series. Every per-cut
reading then splits, and nothing fails: the numbers are right, the population is wrong.

The other half of the problem is a dimension the model never had. An attribute index is
measured *per attribute* («hamburguesas deliciosas», «café»), and with nowhere to put it the
reader packed it into the segment — «calidad de la comida | sd» — or dropped it, collapsing
eight attributes onto one coordinate where they read as contradicting each other. The
attribute is its own dimension and travels beside the segment, not inside it.
"""
from __future__ import annotations

import re
import unicodedata
from typing import Iterable, Optional, Tuple

#: Formas declaradas que NO se pueden deducir: iniciales y abreviaturas con punto. Un
#: prefijo se resuelve por regla (ver ``resolve_segment``); «sd» no es prefijo de nada, es
#: una inicial, y adivinarla sería lo mismo que inventarla. Se declaran y se prueban.
SEGMENT_ALIASES: dict[str, str] = {
    "sd": "santo domingo",
    "sto domingo": "santo domingo",
    "sto dgo": "santo domingo",
    "s domingo": "santo domingo",
    "st": "santiago",
    "stgo": "santiago",
    "sgo": "santiago",
    "sg": "santiago",
    "tot": "total",
    "nse bc+": "bc+",
    "nse c/c-": "c/c-",
    "nse d": "d",
}

_WS = re.compile(r"\s+")


def _fold(text: str) -> str:
    """Minúsculas, sin acentos y sin puntuación de abreviatura, para COMPARAR."""
    decomposed = unicodedata.normalize("NFD", text or "")
    stripped = "".join(c for c in decomposed if unicodedata.category(c) != "Mn")
    limpio = stripped.lower().replace(".", " ").replace(",", " ")
    return _WS.sub(" ", limpio).strip()


def split_attribute(raw: Optional[str]) -> Tuple[Optional[str], str]:
    """Parte «atributo | corte» en sus dos dimensiones.

    El lector de láminas empaqueta las dos con una barra cuando la rejilla las cruza. Sin
    separarlas, el enunciado de la pregunta entra como si fuera una población.
    """
    texto = (raw or "").strip()
    if "|" not in texto:
        return None, texto or "total"
    izquierda, _, derecha = texto.partition("|")
    atributo = izquierda.strip() or None
    corte = derecha.strip() or "total"
    return atributo, corte


def resolve_segment(raw: Optional[str], known: Iterable[str] = ()) -> str:
    """La forma canónica de un corte.

    Orden: alias declarado → coincidencia exacta contra lo YA presente en el encargo →
    prefijo de palabras de UN solo corte conocido → el propio rótulo normalizado.

    Lo ya presente manda sobre cualquier tabla nuestra: si el encargo viene escribiendo
    «santo domingo», una entrega que traiga «SD» tiene que caer ahí y no crear una segunda
    forma. La ambigüedad se rechaza —dos candidatos y no se elige ninguno—, igual que en el
    resolvedor de marcas.
    """
    plegado = _fold(raw or "")
    if not plegado:
        return "total"

    conocidos = {_fold(k): k.strip() for k in known if (k or "").strip()}

    alias = SEGMENT_ALIASES.get(plegado)
    if alias:
        # El alias apunta a una forma canónica; si el encargo ya la escribe distinto pero
        # equivalente, gana la del encargo.
        return conocidos.get(_fold(alias), alias)

    if plegado in conocidos:
        return conocidos[plegado]

    palabras = plegado.split()
    if len(plegado) >= 4:
        candidatos = {
            valor for clave, valor in conocidos.items()
            if clave != plegado and clave.split()[: len(palabras)] == palabras
        }
        if len(candidatos) == 1:
            return next(iter(candidatos))

    return plegado


def normalize_cut(
    raw: Optional[str], known: Iterable[str] = ()
) -> Tuple[Optional[str], str]:
    """Las dos dimensiones de UN SOLO rótulo: ``(atributo, corte canónico)``.

    Solo para la forma EMPAQUETADA («calidad de la comida | sd»). Si el atributo llega en
    su propio campo, usá ``normalize_dimensions``: pasarle el texto suelto a esta función
    lo devuelve como CORTE y el atributo se pierde. Pasó en producción —una relectura
    entera del mazo con 247 celdas sin atributo— porque el camino del campo dedicado nunca
    se probó: los tests cubrían la forma empaquetada y el corte a secas.
    """
    atributo, corte = split_attribute(raw)
    return (atributo.strip() if atributo else None), resolve_segment(corte, known)


def normalize_dimensions(
    attribute: Optional[str], segment: Optional[str], known: Iterable[str] = ()
) -> Tuple[Optional[str], str]:
    """Las dos dimensiones desde sus DOS campos, como las entrega el esquema nuevo.

    Un atributo en su propio campo ES el atributo: no se reinterpreta. Si viene vacío, se
    intenta desempaquetarlo del rótulo del corte, que es como llegaba antes de que el
    esquema tuviera dónde ponerlo. Una sola función para las tres rutas de ingesta —mazo,
    plantilla y recanonización— porque tres copias de esta decisión divergen.
    """
    propio = (attribute or "").strip()
    if propio:
        return propio, resolve_segment(segment, known)
    return normalize_cut(segment, known)
