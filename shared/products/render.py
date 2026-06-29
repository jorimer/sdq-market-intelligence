"""Renderer PDF genérico, sector-agnóstico — línea base de la receta de onboarding.

Cualquier sector que NO tenga su propio generador rico (como sí lo tiene banking con
su radar) usa este renderer para producir el PDF de un nivel: portada de marca +
tablas de datos opcionales + secciones narrativas + marca por nivel / estampa de
muestra. Vive en ``shared/`` para que ningún sector tenga que importar a otro.

Markdown ligero en las narrativas (encabezados, **negrita**, viñetas) — sin tofu de
glifos. No duplica la lógica de dominio de banking; es deliberadamente simple.
"""
from __future__ import annotations

import os
import re
from datetime import datetime
from typing import Dict, List, Optional, Sequence, Tuple

from reportlab.lib.colors import HexColor
from reportlab.lib.enums import TA_CENTER, TA_JUSTIFY
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import inch
from reportlab.platypus import (
    PageBreak,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)

from shared.config.settings import settings

NAVY = HexColor("#1A365D")
BLUE = HexColor("#2B6CB0")
GRAY = HexColor("#718096")
LIGHT_GRAY = HexColor("#F7FAFC")
WHITE = HexColor("#FFFFFF")
MARGIN = 0.75 * inch

DISCLAIMER_ES = (
    "Las opiniones expresadas en este informe son de SDQ Consulting y no constituyen "
    "una recomendación de inversión. SDQ no asume responsabilidad por pérdidas "
    "derivadas del uso de esta información."
)

_GLYPH_RE = re.compile("[▀-▟■-◿✀-➿☀-⛿\U0001f000-\U0001ffff️]")


def _styles():
    s = getSampleStyleSheet()
    s.add(ParagraphStyle("PTitle", parent=s["Title"], fontSize=24, textColor=NAVY,
                         alignment=TA_CENTER, spaceAfter=18))
    s.add(ParagraphStyle("PHead", parent=s["Heading1"], fontSize=15, textColor=NAVY,
                         spaceBefore=14, spaceAfter=10))
    s.add(ParagraphStyle("PSub", parent=s["Heading2"], fontSize=12, textColor=BLUE,
                         spaceBefore=10, spaceAfter=6))
    s.add(ParagraphStyle("PBody", parent=s["Normal"], fontSize=10, leading=14,
                         alignment=TA_JUSTIFY, spaceAfter=6))
    s.add(ParagraphStyle("PBullet", parent=s["Normal"], fontSize=10, leading=14,
                         leftIndent=12, spaceAfter=4))
    s.add(ParagraphStyle("PSmall", parent=s["Normal"], fontSize=8, textColor=GRAY, leading=10))
    return s


def _inline(text: str) -> str:
    text = _GLYPH_RE.sub("", text)
    text = text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    return re.sub(r"\*\*([^*]+)\*\*", r"<b>\1</b>", text).strip()


def _narrative_flowables(narratives: Dict[str, str], titles: Dict[str, str], styles) -> List:
    out: List = []
    for key, text in narratives.items():
        out.append(Paragraph(titles.get(key, key.replace("_", " ").title()), styles["PHead"]))
        for raw in (text or "").replace("\r", "").split("\n"):
            line = raw.strip()
            if not line:
                continue
            h = re.match(r"^(#{1,3})\s+(.*)$", line)
            if h:
                out.append(Paragraph(_inline(h.group(2)), styles["PSub"]))
            elif re.match(r"^(?:[-*]|\d+[.)])\s+", line):
                out.append(Paragraph("•&nbsp; " + _inline(re.sub(r"^(?:[-*]|\d+[.)])\s+", "", line)),
                                     styles["PBullet"]))
            else:
                out.append(Paragraph(_inline(line), styles["PBody"]))
        out.append(Spacer(1, 0.15 * inch))
    return out


def _data_table(heading: str, rows: Sequence[Sequence[str]], styles) -> List:
    out: List = [Paragraph(heading, styles["PHead"])]
    data = [[Paragraph(_inline(str(c)), styles["PSmall"]) for c in r] for r in rows]
    ncol = max((len(r) for r in data), default=1)
    table = Table(data, colWidths=[(6.5 * inch) / ncol] * ncol)
    table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), NAVY),
        ("TEXTCOLOR", (0, 0), (-1, 0), WHITE),
        ("GRID", (0, 0), (-1, -1), 0.5, GRAY),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [WHITE, LIGHT_GRAY]),
        ("TOPPADDING", (0, 0), (-1, -1), 4), ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
    ]))
    out.append(table)
    out.append(Spacer(1, 0.2 * inch))
    return out


def _decorator(watermark: Optional[str], sample: bool):
    text = "MUESTRA — DATA ILUSTRATIVA" if sample else watermark
    if not text:
        return None
    color = HexColor("#991B1B") if sample else GRAY

    def _draw(canvas, doc):
        canvas.saveState()
        canvas.setFont("Helvetica-Bold" if sample else "Helvetica", 8)
        canvas.setFillColor(color)
        canvas.drawCentredString(A4[0] / 2, 0.4 * inch, text)
        canvas.restoreState()

    return _draw


def render_product_pdf(
    *,
    sector_key: str,
    display_name: str,
    title: str,
    period: str,
    narratives: Dict[str, str],
    section_titles: Optional[Dict[str, str]] = None,
    tables: Optional[List[Tuple[str, Sequence[Sequence[str]]]]] = None,
    subtitle: Optional[str] = None,
    watermark: Optional[str] = None,
    sample: bool = False,
    output_dir: Optional[str] = None,
) -> str:
    """Renderiza un PDF genérico de producto y devuelve el path.

    Portada (display_name + título + período [+ subtítulo]) → tablas de datos →
    secciones narrativas → disclaimer. ``watermark``/``sample`` dibujan marca por página.
    """
    out_dir = output_dir or settings.REPORTS_DIR
    os.makedirs(out_dir, exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    safe = re.sub(r"[^a-z0-9]+", "_", display_name.lower()).strip("_")
    path = os.path.join(out_dir, f"{sector_key}_{safe}_{ts}.pdf")

    # Títulos de las secciones ESTÁNDAR auto-generadas (metodología/fuentes): se mergean
    # como default para que el PDF las titule bien aunque el producto no las declare.
    from shared.products.report_sections import STANDARD_SECTION_TITLES
    section_titles = {**STANDARD_SECTION_TITLES, **(section_titles or {})}

    styles = _styles()
    el: List = [
        Spacer(1, 1.3 * inch),
        Paragraph("SDQ Market Intelligence", styles["PTitle"]),
        Spacer(1, 0.2 * inch),
        Paragraph(title, styles["PHead"]),
        Spacer(1, 0.3 * inch),
        Paragraph(display_name, styles["PTitle"]),
    ]
    if subtitle:
        el.append(Paragraph(subtitle, styles["PSub"]))
    el += [
        Spacer(1, 0.3 * inch),
        Paragraph(f"Período: {period}", styles["PBody"]),
        Paragraph(f"Fecha: {datetime.now().strftime('%d/%m/%Y')}", styles["PBody"]),
        PageBreak(),
    ]
    for heading, rows in (tables or []):
        if rows:
            el += _data_table(heading, rows, styles)
    el += _narrative_flowables(narratives, section_titles or {}, styles)
    el += [Spacer(1, 0.4 * inch), Paragraph("Disclaimer", styles["PSub"]),
           Paragraph(DISCLAIMER_ES, styles["PSmall"])]

    doc = SimpleDocTemplate(path, pagesize=A4, leftMargin=MARGIN, rightMargin=MARGIN,
                            topMargin=MARGIN, bottomMargin=MARGIN,
                            title=f"SDQ — {title} — {display_name}", author="SDQ Market Intelligence")
    dec = _decorator(watermark, sample)
    if dec:
        doc.build(el, onFirstPage=dec, onLaterPages=dec)
    else:
        doc.build(el)
    return path
