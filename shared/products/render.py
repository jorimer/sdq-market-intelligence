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
    HRFlowable,
    Image,
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
SIGNAL = HexColor("#E11D48")   # signal red — acento de marca (pull-quotes, barras)
GRAY = HexColor("#718096")
LIGHT_GRAY = HexColor("#F7FAFC")
RULE = HexColor("#E2E8F0")
SAMPLE_RED = HexColor("#991B1B")
WHITE = HexColor("#FFFFFF")
MARGIN = 0.75 * inch
CONTENT_W = A4[0] - 2 * MARGIN
# Alto máximo de una imagen embebida: debe caber en el marco de página tras el furniture
# (cabecera/pie). Un gráfico más alto se escala hacia abajo en vez de romper el layout.
MAX_IMG_H = A4[1] - 2 * MARGIN - 1.25 * inch

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
    # Marca: kicker + título de portada (sobre banda navy, texto blanco) + pull-quote.
    s.add(ParagraphStyle("CoverKicker", parent=s["Normal"], fontSize=11, textColor=WHITE,
                         leading=14, spaceAfter=6))
    s.add(ParagraphStyle("CoverTitle", parent=s["Title"], fontSize=26, textColor=WHITE,
                         alignment=0, leading=30, spaceAfter=0))
    s.add(ParagraphStyle("CoverMeta", parent=s["Normal"], fontSize=11, textColor=NAVY, leading=16))
    s.add(ParagraphStyle("PullQuote", parent=s["Normal"], fontSize=13, textColor=NAVY,
                         leading=18, leftIndent=10, spaceBefore=4, spaceAfter=4))
    return s


def _inline(text: str) -> str:
    text = _GLYPH_RE.sub("", text)
    text = text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    return re.sub(r"\*\*([^*]+)\*\*", r"<b>\1</b>", text).strip()


def _pull_quote(text: str, styles) -> Table:
    """Pull-quote de marca: barra de acento signal-red + texto grande (cifra/insight clave)."""
    t = Table([["", Paragraph(_inline(text), styles["PullQuote"])]],
              colWidths=[0.06 * inch, CONTENT_W - 0.06 * inch])
    t.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (0, 0), SIGNAL),
        ("LEFTPADDING", (1, 0), (1, 0), 10), ("RIGHTPADDING", (0, 0), (-1, -1), 2),
        ("TOPPADDING", (0, 0), (-1, -1), 6), ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
    ]))
    return t


def _md_split_row(line: str) -> List[str]:
    return [c.strip() for c in line.strip().strip("|").split("|")]


def _md_is_sep(line: str) -> bool:
    """Fila separadora de tabla markdown: `|---|:--:|---|`."""
    t = line.strip()
    return "-" in t and "|" in t and all(
        re.fullmatch(r":?-{1,}:?", c) for c in _md_split_row(t))


def _md_table_flowable(header: List[str], rows: Sequence[Sequence[str]], styles) -> Table:
    """Tabla markdown → tabla branded (mismo look que las tablas de datos del reporte)."""
    ncol = len(header) or 1
    data = [[Paragraph(_inline(str(c)), styles["PSmall"]) for c in header]]
    for r in rows:
        cells = (list(r) + [""] * ncol)[:ncol]
        data.append([Paragraph(_inline(str(c)), styles["PSmall"]) for c in cells])
    table = Table(data, colWidths=[(6.5 * inch) / ncol] * ncol, repeatRows=1)
    table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), NAVY),
        ("TEXTCOLOR", (0, 0), (-1, 0), WHITE),
        ("GRID", (0, 0), (-1, -1), 0.5, GRAY),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [WHITE, LIGHT_GRAY]),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("TOPPADDING", (0, 0), (-1, -1), 4), ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
        ("LEFTPADDING", (0, 0), (-1, -1), 5),
    ]))
    return table


def md_flowables(text: str, styles) -> List:
    """Markdown de marca → flowables ReportLab: tablas branded, `---` divisor, `> `
    pull-quote signal-red, `#` subtítulo, viñetas y párrafos. Reutilizable por cualquier
    generador (catálogo + insight drill-down) para una salida 1:1 con el estándar."""
    out: List = []
    lines = (text or "").replace("\r", "").split("\n")
    i = 0
    while i < len(lines):
        line = lines[i].strip()
        if not line:
            i += 1
            continue
        # Tabla markdown: fila de encabezado + fila separadora + cuerpo.
        if "|" in line and i + 1 < len(lines) and _md_is_sep(lines[i + 1]):
            header = _md_split_row(line)
            body: List[List[str]] = []
            j = i + 2
            while j < len(lines) and "|" in lines[j] and lines[j].strip():
                body.append(_md_split_row(lines[j]))
                j += 1
            out.append(_md_table_flowable(header, body, styles))
            out.append(Spacer(1, 0.08 * inch))
            i = j
            continue
        # Regla horizontal (`---`) → divisor fino, no texto literal.
        if re.fullmatch(r"-{3,}", line):
            out.append(HRFlowable(width="100%", thickness=0.5, color=RULE,
                                  spaceBefore=4, spaceAfter=4))
            i += 1
            continue
        q = re.match(r"^>\s+(.*)$", line)          # blockquote → pull-quote de marca
        h = re.match(r"^(#{1,3})\s+(.*)$", line)
        if q:
            out.append(_pull_quote(q.group(1), styles))
        elif h:
            out.append(Paragraph(_inline(h.group(2)), styles["PSub"]))
        elif re.match(r"^(?:[-*]|\d+[.)])\s+", line):
            out.append(Paragraph("•&nbsp; " + _inline(re.sub(r"^(?:[-*]|\d+[.)])\s+", "", line)),
                                 styles["PBullet"]))
        else:
            out.append(Paragraph(_inline(line), styles["PBody"]))
        i += 1
    return out


def _narrative_flowables(narratives: Dict[str, str], titles: Dict[str, str], styles) -> List:
    out: List = []
    for n, (key, text) in enumerate(narratives.items(), start=1):
        title = titles.get(key, key.replace("_", " ").title())
        out.append(Paragraph(f"{n}.&nbsp; {_inline(title)}", styles["PHead"]))
        out += md_flowables(text, styles)
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


def _draw_logo(canvas, x: float, y: float, s: float) -> None:
    """Marca 'Arco' de SDQ·MIP: cuadrado redondeado de acento + arco blanco + punto.
    Reproduce el logo del producto (frontend ArcMark) en el PDF. (x, y) = esquina inf-izq."""
    canvas.saveState()
    canvas.setFillColor(BLUE)
    canvas.roundRect(x, y, s, s, s * 0.28, fill=1, stroke=0)
    cx, cy, r = x + s / 2, y + s / 2, s * 0.27
    canvas.setStrokeColor(WHITE)
    canvas.setLineWidth(max(1.0, s * 0.11))
    canvas.setLineCap(1)
    p = canvas.beginPath()
    p.arc(cx - r, cy - r, cx + r, cy + r, 130, 300)   # ~3/4 de anillo (hueco arriba)
    canvas.drawPath(p, stroke=1, fill=0)
    canvas.setFillColor(WHITE)
    canvas.circle(cx, cy + r, s * 0.085, fill=1, stroke=0)   # punto superior
    canvas.restoreState()


def _furniture(header_line: str, watermark: Optional[str], sample: bool, *, first: bool):
    """Guarnición de página: logo + encabezado corrido + regla + nº de página (interiores) y
    watermark/estampa al pie (todas). La portada (first) lleva el logo grande, sin encabezado."""
    wm = "MUESTRA — DATA ILUSTRATIVA" if sample else watermark
    w, h = A4

    def _draw(canvas, doc):
        canvas.saveState()
        if first:
            _draw_logo(canvas, MARGIN, h - 0.98 * inch, 0.46 * inch)
        else:
            _draw_logo(canvas, MARGIN, h - 0.52 * inch, 0.18 * inch)
            canvas.setFont("Helvetica-Bold", 8)
            canvas.setFillColor(NAVY)
            canvas.drawString(MARGIN + 0.27 * inch, h - 0.48 * inch, header_line[:104])
            canvas.setStrokeColor(RULE)
            canvas.setLineWidth(0.5)
            canvas.line(MARGIN, h - 0.6 * inch, w - MARGIN, h - 0.6 * inch)
            canvas.setFont("Helvetica", 8)
            canvas.setFillColor(GRAY)
            canvas.drawRightString(w - MARGIN, 0.45 * inch, str(canvas.getPageNumber()))
        if wm:
            canvas.setFont("Helvetica-Bold" if sample else "Helvetica", 8)
            canvas.setFillColor(SAMPLE_RED if sample else GRAY)
            canvas.drawCentredString(w / 2, 0.45 * inch, wm)
        canvas.restoreState()

    return _draw


def _cover(title: str, display_name: str, period: str, subtitle: Optional[str],
           headline: Optional[str], styles) -> List:
    """Portada de marca: banda navy con 'MARKET INTELLIGENCE REPORT' + título, y metadatos."""
    band = Table(
        [[Paragraph("SDQ·MIP · MARKET INTELLIGENCE REPORT", styles["CoverKicker"])],
         [Paragraph(_inline(title), styles["CoverTitle"])]],
        colWidths=[CONTENT_W])
    band.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), NAVY),
        ("LEFTPADDING", (0, 0), (-1, -1), 18), ("RIGHTPADDING", (0, 0), (-1, -1), 18),
        ("TOPPADDING", (0, 0), (0, 0), 18), ("BOTTOMPADDING", (0, 0), (0, 0), 2),
        ("TOPPADDING", (0, 1), (0, 1), 2), ("BOTTOMPADDING", (0, 1), (0, 1), 20),
    ]))
    # El sujeto de portada (``display_name``) es, en el motor de research, la PREGUNTA del
    # cliente —que puede ser larga—. A 24pt fijo se cortaba/desbordaba; se escala el cuerpo
    # según el largo para que la pregunta ENTERA quede legible sin truncar en la portada.
    dn = len(display_name or "")
    subj_fs = 24 if dn <= 80 else 20 if dn <= 160 else 16 if dn <= 280 else 13
    subj_style = ParagraphStyle("PTitleDyn", parent=styles["PTitle"],
                                fontSize=subj_fs, leading=round(subj_fs * 1.2))
    out: List = [Spacer(1, 1.1 * inch), band, Spacer(1, 0.45 * inch),
                 Paragraph(_inline(display_name), subj_style)]
    if subtitle:
        out.append(Paragraph(_inline(subtitle), styles["PSub"]))
    if headline:
        out.append(Spacer(1, 0.1 * inch))
        out.append(_pull_quote(headline, styles))
    out += [Spacer(1, 0.4 * inch),
            Paragraph(f"<b>Período:</b> {period}", styles["CoverMeta"]),
            Paragraph(f"<b>Fecha:</b> {datetime.now().strftime('%d/%m/%Y')}", styles["CoverMeta"]),
            PageBreak()]
    return out


def _img_ratio(path: str) -> float:
    """Alto/ancho de un PNG (para escalar a ancho de contenido sin deformar)."""
    try:
        from reportlab.lib.utils import ImageReader
        w, h = ImageReader(path).getSize()
        return (h / w) if w else 0.55
    except Exception:  # noqa: BLE001
        return 0.55


def build_branded_pdf(
    *,
    path: str,
    title: str,
    display_name: str,
    period: str,
    body: List,
    subtitle: Optional[str] = None,
    headline: Optional[str] = None,
    watermark: Optional[str] = None,
    sample: bool = False,
    add_disclaimer: bool = True,
) -> str:
    """Shell de documento de marca: portada (banda navy + logo Arco + sujeto + headline) →
    *body* (flowables ya armados por el llamador) → disclaimer opcional; cada página con
    encabezado corrido + logo pequeño + nº de página + watermark/estampa de muestra.

    Punto de unión del estándar de marca para generadores con CUERPO PROPIO (p.ej. banking,
    que arma su radar y tablas con estilos propios) sin duplicar el chrome de ``render.py``.
    Devuelve *path*."""
    styles = _styles()
    el: List = _cover(title, display_name, period, subtitle, headline, styles)
    el += list(body or [])
    if add_disclaimer:
        el += [Spacer(1, 0.4 * inch), Paragraph("Disclaimer", styles["PSub"]),
               Paragraph(DISCLAIMER_ES, styles["PSmall"])]
    header_line = f"SDQ·MIP — {title} · {display_name}"
    doc = SimpleDocTemplate(path, pagesize=A4, leftMargin=MARGIN, rightMargin=MARGIN,
                            topMargin=MARGIN, bottomMargin=MARGIN,
                            title=f"SDQ — {title} — {display_name}", author="SDQ Market Intelligence")
    doc.build(el,
              onFirstPage=_furniture(header_line, watermark, sample, first=True),
              onLaterPages=_furniture(header_line, watermark, sample, first=False))
    return path


def build_insight_branded_pdf(
    *,
    path: str,
    title: str,
    display_name: str,
    period: str = "",
    body_md: str,
    subtitle: Optional[str] = None,
    headline: Optional[str] = None,
    watermark: Optional[str] = None,
) -> str:
    """Insight drill-down de un eje → MISMO chrome de marca que el catálogo: portada (banda
    navy + logo Arco), pull-quotes, subtítulos, tablas. El cuerpo llega en Markdown (ya
    generado por Claude) y se convierte con ``md_flowables``. Escribe a *path* y lo devuelve."""
    styles = _styles()
    return build_branded_pdf(
        path=path, title=title, display_name=display_name, period=period,
        body=md_flowables(body_md, styles), subtitle=subtitle, headline=headline,
        watermark=watermark)


def render_product_pdf(
    *,
    sector_key: str,
    display_name: str,
    title: str,
    period: str,
    narratives: Dict[str, str],
    section_titles: Optional[Dict[str, str]] = None,
    tables: Optional[List[Tuple[str, Sequence[Sequence[str]]]]] = None,
    charts: Optional[List[dict]] = None,
    subtitle: Optional[str] = None,
    headline: Optional[str] = None,
    watermark: Optional[str] = None,
    sample: bool = False,
    output_dir: Optional[str] = None,
    fmt: str = "pdf",
) -> str:
    """Renderiza el reporte de marca de un producto y devuelve el path (docs/REPORT_STANDARD.md).

    Portada de marca (banda + logo + título + sujeto + período [+ subtítulo/headline]) →
    tablas → secciones narrativas numeradas (con pull-quotes) → disclaimer. Cada página
    interior lleva encabezado corrido + nº de página; ``watermark``/``sample`` estampan el
    pie por tier. ``headline`` es la cifra/banda clave para el pull-quote de portada.
    ``fmt="docx"`` produce el Word equivalente (misma anatomía) — punto de entrada único.
    """
    if fmt == "docx":
        from shared.products.render_docx import render_product_docx
        return render_product_docx(
            sector_key=sector_key, display_name=display_name, title=title, period=period,
            narratives=narratives, section_titles=section_titles, tables=tables, charts=charts,
            subtitle=subtitle, headline=headline, watermark=watermark, sample=sample,
            output_dir=output_dir)
    out_dir = output_dir or settings.REPORTS_DIR
    os.makedirs(out_dir, exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    # Acotar el slug: el display_name puede ser una pregunta larga (motor de research) y un
    # nombre de archivo >255 chars rompe el guardado (OSError). El sufijo timestamp lo hace único.
    safe = re.sub(r"[^a-z0-9]+", "_", display_name.lower()).strip("_")[:80].rstrip("_")
    path = os.path.join(out_dir, f"{sector_key}_{safe}_{ts}.pdf")

    # Títulos de las secciones ESTÁNDAR auto-generadas (metodología/fuentes): se mergean
    # como default para que el PDF las titule bien aunque el producto no las declare.
    from shared.products.report_sections import STANDARD_SECTION_TITLES
    section_titles = {**STANDARD_SECTION_TITLES, **(section_titles or {})}

    styles = _styles()
    body: List = []
    # Gráficos de marca (barras de dimensión/contribución, línea de tendencia) — PNG embebido.
    from shared.products.charts import render_charts
    for _ctitle, png in render_charts(charts, out_dir, f"{sector_key}_{ts}"):
        # Escalar a ancho de contenido; pero si un gráfico "alto" (muchas barras, p.ej. la
        # trayectoria WGI de 26 años) excede el alto útil de página, cap por ALTO y reduce
        # el ancho — antes tiraba LayoutError → 500 al descargar el PDF (bug real).
        ratio = _img_ratio(png)
        w, h = CONTENT_W, CONTENT_W * ratio
        if ratio > 0 and h > MAX_IMG_H:
            h, w = MAX_IMG_H, MAX_IMG_H / ratio
        body.append(Image(png, width=w, height=h))
        body.append(Spacer(1, 0.2 * inch))
    for heading, rows in (tables or []):
        if rows:
            body += _data_table(heading, rows, styles)
    body += _narrative_flowables(narratives, section_titles or {}, styles)

    return build_branded_pdf(
        path=path, title=title, display_name=display_name, period=period, body=body,
        subtitle=subtitle, headline=headline, watermark=watermark, sample=sample)
