"""Branded SDQ·MIP insight → PDF.

Delega en el shell de marca compartido (``build_insight_branded_pdf`` en
``shared/products/render.py``) para renderizar un único insight de IA (cuerpo
Markdown + metadata) con paridad 1:1 frente a los reportes Pulse/Insight/Deep.

Pure: toma el texto que el cliente ya tiene (sin llamada a Claude, sin DB) y
devuelve los bytes del PDF.
"""
from typing import Optional


def build_insight_pdf(
    *,
    title: str,
    body_md: str,
    eyebrow: Optional[str] = None,
    subtitle: Optional[str] = None,
    meta: Optional[str] = None,
    lang: str = "es",
) -> bytes:
    """Render one drill-down insight (Markdown *body_md* + metadata) into a PDF; returns bytes.

    Usa el MISMO chrome de marca que el catálogo de productos (portada con banda navy + logo
    Arco, pull-quotes, subtítulos, tablas) vía ``build_insight_branded_pdf`` — paridad 1:1 con
    los reportes Pulse/Insight/Deep. *eyebrow* = eje/fuente (sujeto de portada); *subtitle* =
    entidad/audiencia; *meta* = profundidad/período.
    """
    import os
    import tempfile

    from shared.products.render import build_insight_branded_pdf

    fd, path = tempfile.mkstemp(suffix=".pdf")
    os.close(fd)
    try:
        build_insight_branded_pdf(
            path=path, title=title,
            display_name=eyebrow or "SDQ · Market Intelligence",
            period=meta or "", body_md=body_md, subtitle=subtitle)
        with open(path, "rb") as f:
            return f.read()
    finally:
        try:
            os.remove(path)
        except OSError:
            pass
