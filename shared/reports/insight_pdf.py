"""Branded SDQ·MIP insight → PDF (ReportLab).

Self-contained (no `modules.*` imports — `shared` is transversal): renders a single
AI insight (Markdown body + metadata) into a branded one-pager. The Markdown helpers
mirror the banking report generator but live here so any axis can produce an insight PDF.

Pure: takes the text the client already has (no Claude call, no DB), returns PDF bytes.
"""
import io
import re
from datetime import datetime, timezone
from typing import List, Optional

from reportlab.lib.colors import HexColor
from reportlab.lib.enums import TA_JUSTIFY
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import inch
from reportlab.platypus import (
    HRFlowable,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)

# ── Brand constants (mirror banking_score/reports/pdf_generator) ───────────────
NAVY = HexColor("#1A365D")
BLUE = HexColor("#2B6CB0")
GRAY = HexColor("#718096")
LIGHT_GRAY = HexColor("#F7FAFC")
WHITE = HexColor("#FFFFFF")
MARGIN = 0.75 * inch

DISCLAIMER = {
    "es": (
        "Este análisis es generado con apoyo de IA (Claude) sobre datos de fuentes oficiales y se "
        "ofrece con fines informativos. No constituye una recomendación de inversión ni asesoría "
        "financiera. SDQ Consulting no asume responsabilidad por decisiones tomadas con base en esta "
        "información; verifique las cifras contra la fuente original."
    ),
    "en": (
        "This analysis is generated with AI assistance (Claude) over official-source data and is "
        "provided for informational purposes only. It is not investment advice or a recommendation. "
        "SDQ Consulting assumes no liability for decisions based on this information; verify the figures "
        "against the original source."
    ),
    "fr": (
        "Cette analyse est générée avec l'aide de l'IA (Claude) à partir de données de sources "
        "officielles, à titre informatif uniquement. Elle ne constitue pas un conseil en investissement. "
        "SDQ Consulting décline toute responsabilité quant aux décisions prises sur la base de ces "
        "informations ; vérifiez les chiffres auprès de la source d'origine."
    ),
}
DISCLAIMER_TITLE = {"es": "Aviso", "en": "Disclaimer", "fr": "Avertissement"}
GENERATED_LABEL = {"es": "Generado", "en": "Generated", "fr": "Généré"}
LOCALES = {"es": "es-DO", "en": "en-US", "fr": "fr-FR"}

_GLYPH_RE = re.compile("[▀-▟■-◿✀-➿☀-⛿\U0001f000-\U0001ffff️]")


def _styles():
    s = getSampleStyleSheet()
    s.add(ParagraphStyle("InEyebrow", parent=s["Normal"], fontSize=8.5, textColor=BLUE,
                         leading=11, spaceAfter=2, fontName="Helvetica-Bold"))
    s.add(ParagraphStyle("InTitle", parent=s["Title"], fontSize=20, textColor=NAVY,
                         alignment=0, spaceAfter=4, leading=24))
    s.add(ParagraphStyle("InMeta", parent=s["Normal"], fontSize=9, textColor=GRAY, spaceAfter=2))
    s.add(ParagraphStyle("InBody", parent=s["Normal"], fontSize=10.5, leading=15,
                         spaceAfter=8, alignment=TA_JUSTIFY))
    s.add(ParagraphStyle("InBodyBold", parent=s["Normal"], fontSize=11, leading=15,
                         spaceAfter=4, spaceBefore=8, textColor=NAVY, fontName="Helvetica-Bold"))
    s.add(ParagraphStyle("InSubHeading", parent=s["Heading2"], fontSize=13, textColor=BLUE,
                         spaceAfter=6, spaceBefore=12))
    s.add(ParagraphStyle("InBullet", parent=s["Normal"], fontSize=10.5, leading=15,
                         spaceAfter=4, leftIndent=12, alignment=TA_JUSTIFY))
    s.add(ParagraphStyle("InSmall", parent=s["Normal"], fontSize=8, textColor=GRAY, leading=11))
    s.add(ParagraphStyle("InWordmark", parent=s["Normal"], fontSize=12, textColor=NAVY,
                         fontName="Helvetica-Bold"))
    s.add(ParagraphStyle("InTableHead", parent=s["Normal"], fontSize=8.5, leading=11,
                         textColor=WHITE, fontName="Helvetica-Bold"))
    s.add(ParagraphStyle("InTableCell", parent=s["Normal"], fontSize=8.5, leading=11))
    return s


# ── Markdown → flowables (mirrors the banking renderer) ────────────────────────
def _md_inline(text: str) -> str:
    text = _GLYPH_RE.sub("", text)
    text = text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    text = re.sub(r"\*\*([^*]+)\*\*", r"<b>\1</b>", text)
    return text.strip()


def _md_split_row(line: str) -> List[str]:
    return [c.strip() for c in line.strip().strip("|").split("|")]


def _md_is_sep(line: str) -> bool:
    t = line.strip()
    return "-" in t and "|" in t and all(re.fullmatch(r":?-{1,}:?", c) for c in _md_split_row(t))


def _md_table(header: List[str], rows: List[List[str]], styles) -> Table:
    data = [[Paragraph(_md_inline(c), styles["InTableHead"]) for c in header]]
    for r in rows:
        cells = (r + [""] * len(header))[: len(header)]
        data.append([Paragraph(_md_inline(c), styles["InTableCell"]) for c in cells])
    ncol = len(header) or 1
    table = Table(data, colWidths=[(6.5 * inch) / ncol] * ncol, repeatRows=1)
    table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), NAVY),
        ("GRID", (0, 0), (-1, -1), 0.5, GRAY),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [WHITE, LIGHT_GRAY]),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("TOPPADDING", (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
        ("LEFTPADDING", (0, 0), (-1, -1), 5),
    ]))
    return table


def _md_to_flowables(text: str, styles) -> List:
    out: List = []
    lines = (text or "").replace("\r", "").split("\n")
    i = 0
    while i < len(lines):
        line = lines[i].strip()
        if not line:
            i += 1
            continue
        if "|" in line and i + 1 < len(lines) and _md_is_sep(lines[i + 1]):
            header = _md_split_row(line)
            body: List[List[str]] = []
            j = i + 2
            while j < len(lines) and "|" in lines[j] and lines[j].strip():
                body.append(_md_split_row(lines[j]))
                j += 1
            out.append(_md_table(header, body, styles))
            out.append(Spacer(1, 0.08 * inch))
            i = j
            continue
        if re.fullmatch(r"-{3,}", line):
            out.append(HRFlowable(width="100%", thickness=0.5, color=LIGHT_GRAY,
                                  spaceBefore=4, spaceAfter=4))
            i += 1
            continue
        h = re.match(r"^(#{1,3})\s+(.*)$", line)
        if h:
            style = styles["InSubHeading"] if len(h.group(1)) <= 2 else styles["InBodyBold"]
            out.append(Paragraph(_md_inline(h.group(2)), style))
            i += 1
            continue
        m = re.match(r"^(?:[-*]|\d+[.)])\s+(.*)$", line)
        if m:
            out.append(Paragraph("•&nbsp; " + _md_inline(m.group(1)), styles["InBullet"]))
            i += 1
            continue
        buf = [line]
        i += 1
        while i < len(lines) and lines[i].strip() and not re.match(
            r"^(#{1,3}\s|[-*]\s|\d+[.)]\s|-{3,}$)", lines[i].strip()
        ) and "|" not in lines[i]:
            buf.append(lines[i].strip())
            i += 1
        out.append(Paragraph(_md_inline(" ".join(buf)), styles["InBody"]))
    return out


def _now_local(lang: str) -> str:
    try:
        return datetime.now(timezone.utc).astimezone().strftime("%d %b %Y, %H:%M")
    except Exception:  # noqa: BLE001
        return datetime.now(timezone.utc).strftime("%d %b %Y, %H:%M")


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
