"""Idioma de la request para las narrativas IA.

El frontend manda el header `X-Lang` (es/en/fr). Una dependencia GLOBAL lo lee y lo
guarda en un ContextVar; el motor de narrativa (`claude_engine`) lo toma por defecto.
Así las narrativas salen en el idioma elegido SIN tocar la firma de los ~13 endpoints
que llaman a `generate()`.

La dependencia y el endpoint corren en el mismo contexto de request (incluso para
endpoints sync vía threadpool: anyio copia el contexto), así que el ContextVar fijado
por la dependencia es visible en `generate()`. En jobs de fondo (sin request) cae al
default 'es'.
"""
import contextvars
from typing import Optional

from fastapi import Header

SUPPORTED_LANGS = {"es", "en", "fr"}
DEFAULT_LANG = "es"

# Nombre del idioma para la directiva del prompt (en el propio idioma destino).
LANG_NAMES = {"es": "español", "en": "English", "fr": "français"}

_lang_ctx: contextvars.ContextVar[str] = contextvars.ContextVar(
    "request_lang", default=DEFAULT_LANG
)


def set_request_lang(lang: Optional[str]) -> str:
    """Fija el idioma de la request (validado contra SUPPORTED_LANGS)."""
    v = (lang or "").strip().lower()
    resolved = v if v in SUPPORTED_LANGS else DEFAULT_LANG
    _lang_ctx.set(resolved)
    return resolved


def get_request_lang() -> str:
    return _lang_ctx.get()


async def resolve_request_lang(
    x_lang: Optional[str] = Header(default=None, alias="X-Lang"),
) -> str:
    """Dependencia GLOBAL: lee el header X-Lang y lo fija en el contexto."""
    return set_request_lang(x_lang)
