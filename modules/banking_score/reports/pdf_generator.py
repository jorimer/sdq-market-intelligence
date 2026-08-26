"""PDF report generation using ReportLab.

Produces branded SDQ Market Intelligence PDFs for 7 report types:
full_rating, scorecard, communique, datawatch, wire, criteria, sector_outlook.

Extracted from financial-analysis-agent/backend/app/services/sdq_report_service.py.
"""
import logging
import os
import re
from datetime import datetime
from typing import Dict, List, Optional

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
from reportlab.lib.colors import HexColor
from reportlab.lib.enums import TA_CENTER, TA_JUSTIFY, TA_LEFT, TA_RIGHT
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import inch
from reportlab.platypus import (
    Flowable,
    HRFlowable,
    Image as RLImage,
    PageBreak,
    Paragraph,
    Spacer,
    Table,
    TableStyle,
)

from modules.banking_score.scoring.amplitude import TRAJECTORY_WINDOW as TRAJECTORY_COLUMNS
from modules.banking_score.scoring.weights import SUB_COMPONENT_WEIGHTS
from shared import brand
from shared.config.settings import settings

logger = logging.getLogger(__name__)

# ── Marca ─────────────────────────────────────────────────────────
# La paleta se LEE de `shared.brand`, nunca se declara acá: este generador y el genérico
# de `shared/products/render.py` tenían dos copias, y las dos quedaron en un azul que la
# aplicación ya no usa. Lo vigila `shared/brand/tests/test_paleta_unica.py`.
NAVY = HexColor(brand.INK)          # tinta: títulos y cabeceras de tabla
BLUE = HexColor(brand.ACCENT_INK)   # texto en acento (subtítulos)
ACCENT = HexColor(brand.ACCENT)     # rellenos de acento: barra del pull-quote
GREEN = HexColor(brand.OK)
LIGHT_GRAY = HexColor(brand.CANVAS)
GRAY = HexColor(brand.MUTED)
WHITE = HexColor(brand.WHITE)

DISCLAIMER_ES = (
    "Las calificaciones y opiniones expresadas en este informe son las de "
    "SDQ Consulting y no constituyen una recomendación para comprar, vender "
    "o mantener valores. SDQ Consulting no asume responsabilidad por pérdidas "
    "derivadas del uso de esta información."
)

REPORT_TYPE_LABELS = {
    "full_rating": "Informe de Calificación Completa",
    "scorecard": "Scorecard",
    "communique": "Comunicado de Prensa",
    "datawatch": "DataWatch",
    "wire": "Wire",
    "criteria": "Criterios de Calificación",
    "sector_outlook": "Perspectiva Sectorial",
    "anuario": "Anuario",
}

# Nivel comercial (metadato de portada/header) → etiqueta ES. Sin este mapeo, el valor
# crudo de ``tier`` (p.ej. "deep_dive") queda impreso tal cual en la portada del PDF —
# bug real detectado en producción ("Informe de Calificación Completa · deep_dive").
TIER_LABELS = {"pulse": "Pulse", "insight": "Insight", "deep_dive": "Deep Dive"}

SUB_COMPONENT_LABELS = {
    "solidez": "Solidez Financiera",
    "calidad": "Calidad de Activos",
    "eficiencia": "Eficiencia y Rentabilidad",
    "liquidez": "Liquidez",
    "diversificacion": "Diversificación",
}

NARRATIVE_SECTION_TITLES = {
    "executive_summary": "Resumen Ejecutivo",
    "solidez_financiera": "Solidez Financiera",
    "calidad_activos": "Calidad de Activos",
    "eficiencia_rentabilidad": "Eficiencia y Rentabilidad",
    "liquidez": "Liquidez",
    "diversificacion": "Diversificación",
    "risk_assessment": "Evaluación de Riesgos",
    "comparative": "Análisis Comparativo",
    "entorno_operativo": "Entorno Operativo",
    "soporte_soberano": "Soporte y Techo Soberano",
    "early_warning": "Alerta Temprana",
    "recommendation": "Recomendación",
    "trend_analysis": "Análisis de Tendencias",
    "sector_outlook": "Perspectiva Sectorial",
    "anuario": "Anuario",
    "system_overview": "Panorama del Sistema",
    "scenario_analysis": "Análisis de Escenarios",
    "limitations": "Limitaciones",
}

# Documento de Criterios — secciones DETERMINISTAS generadas del motor (criteria_doc).
try:
    from modules.banking_score.reports.criteria_doc import (
        SECTION_TITLES as _CRIT_TITLES)
    NARRATIVE_SECTION_TITLES = {**NARRATIVE_SECTION_TITLES, **_CRIT_TITLES}
except ImportError:  # pragma: no cover — el reporte no debe romper por esto
    pass

# Las secciones ESTÁNDAR auto-generadas (metodología/fuentes/glosario, ver
# shared/products/report_sections.py) llegan en ``narratives`` con esas claves. Sin este
# merge, ``_build_narrative_sections`` no las reconoce y cae al fallback
# ``key.replace("_", " ").title()`` → título roto en inglés/snake_case tal cual el código
# ("Std Methodology", "Std Sources") — bug real detectado en producción, visible en la
# portada y en cada página del Informe de Calificación Completa.
try:
    from shared.products.report_sections import STANDARD_SECTION_TITLES as _STD_TITLES
    NARRATIVE_SECTION_TITLES = {**NARRATIVE_SECTION_TITLES, **_STD_TITLES}
except ImportError:  # pragma: no cover — el reporte no debe romper por esto
    pass


# ── Styles ────────────────────────────────────────────────────────

def _get_styles():
    styles = getSampleStyleSheet()
    styles.add(ParagraphStyle(
        "SDQTitle", parent=styles["Title"],
        fontSize=24, textColor=NAVY, spaceAfter=20, alignment=TA_CENTER,
    ))
    styles.add(ParagraphStyle(
        "SDQHeading", parent=styles["Heading1"],
        fontSize=16, textColor=NAVY, spaceAfter=12, spaceBefore=16,
    ))
    styles.add(ParagraphStyle(
        "SDQSubHeading", parent=styles["Heading2"],
        fontSize=13, textColor=BLUE, spaceAfter=8, spaceBefore=12,
    ))
    styles.add(ParagraphStyle(
        "SDQBody", parent=styles["Normal"],
        fontSize=10, leading=14, spaceAfter=8, alignment=TA_JUSTIFY,
    ))
    styles.add(ParagraphStyle(
        "SDQSmall", parent=styles["Normal"],
        fontSize=8, textColor=GRAY, leading=10,
    ))
    styles.add(ParagraphStyle(
        "SDQRating", parent=styles["Title"],
        fontSize=48, alignment=TA_CENTER, spaceAfter=10,
    ))
    # Markdown-narrative styles
    styles.add(ParagraphStyle(
        "SDQBodyBold", parent=styles["Normal"],
        fontSize=10.5, leading=14, spaceAfter=4, spaceBefore=6,
        textColor=NAVY, fontName="Helvetica-Bold",
    ))
    styles.add(ParagraphStyle(
        "SDQBullet", parent=styles["Normal"],
        fontSize=10, leading=14, spaceAfter=4, leftIndent=12, alignment=TA_JUSTIFY,
    ))
    styles.add(ParagraphStyle(
        "SDQTableHead", parent=styles["Normal"],
        fontSize=8.5, leading=11, textColor=WHITE, fontName="Helvetica-Bold",
    ))
    styles.add(ParagraphStyle(
        "SDQTableCell", parent=styles["Normal"],
        fontSize=8.5, leading=11,
    ))
    styles.add(ParagraphStyle(
        "SDQPullQuote", parent=styles["Normal"],
        fontSize=12, textColor=NAVY, leading=16, fontName="Helvetica-Bold",
    ))
    styles.add(ParagraphStyle(
        "SDQTableCellBold", parent=styles["SDQTableCell"], fontName="Helvetica-Bold",
    ))
    return styles


# ── Table factory (fuente única de tablas branded del PDF de banca) ───────────
# TODAS las tablas del reporte se construyen aquí. Motivo: en ReportLab una celda
# que es str PLANO se dibuja en una sola línea y se DESBORDA hacia la columna
# vecina (nunca envuelve) — era la causa raíz del bug de "wrapping" que se veía en
# los labels largos del Entorno Operativo. Al envolver cada celda en un Paragraph,
# el texto respeta el ancho de su columna y salta de línea. Centralizarlo garantiza
# que ningún reporte (actual o futuro) pueda re-introducir el desborde.

_BLACK = HexColor(brand.BODY)   # texto de celda — tinta de cuerpo, no negro puro
_ALIGN_ENUM = {"LEFT": TA_LEFT, "CENTER": TA_CENTER, "RIGHT": TA_RIGHT}


def _branded_table(rows: List[List], col_widths: List[float], styles, *,
                   font_size: float = 8.5, aligns: Optional[List[str]] = None,
                   padding: float = 4, repeat_header: bool = True) -> Table:
    """Construye una tabla de marca envolviendo CADA celda en un Paragraph.

    - Fila 0 = encabezado (fondo navy, texto blanco); resto = cuerpo (texto de cuerpo,
      con bandas de fila alternas).
    - ``aligns[i]`` alinea la columna i (``LEFT``/``CENTER``/``RIGHT``). Default:
      1.ª columna a la izquierda, el resto centradas (el look actual de la reportería).
    - Las celdas que ya son *flowables* (un Paragraph con estilo propio — p.ej. la
      "Lectura" gris del macro, o un label en negrita) pasan intactas.
    - ``font_size`` iguala el tamaño de todas las celdas planas de la tabla.
    """
    ncol = len(col_widths)
    aligns = aligns or (["LEFT"] + ["CENTER"] * (ncol - 1))
    lead = font_size + 2.5
    cache: Dict = {}

    def _style(align: str, header: bool) -> ParagraphStyle:
        key = (align, header)
        st = cache.get(key)
        if st is None:
            st = ParagraphStyle(
                f"_bt_{len(cache)}", fontName="Helvetica", fontSize=font_size,
                leading=lead, alignment=_ALIGN_ENUM.get(align, TA_LEFT),
                textColor=(WHITE if header else _BLACK))
            cache[key] = st
        return st

    def _cell(val, ridx: int, cidx: int):
        if isinstance(val, Flowable):
            return val
        align = aligns[cidx] if cidx < len(aligns) else "CENTER"
        return Paragraph(_md_inline("" if val is None else str(val)),
                         _style(align, ridx == 0))

    data = [[_cell(c, ri, ci) for ci, c in enumerate(r)] for ri, r in enumerate(rows)]
    table = Table(data, colWidths=col_widths, repeatRows=1 if repeat_header else 0)
    table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), NAVY),
        ("GRID", (0, 0), (-1, -1), 0.5, GRAY),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [WHITE, LIGHT_GRAY]),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("TOPPADDING", (0, 0), (-1, -1), padding),
        ("BOTTOMPADDING", (0, 0), (-1, -1), padding),
    ]))
    return table


# ── Radar chart ───────────────────────────────────────────────────

def generate_radar_chart(sub_scores: Dict[str, float], output_path: str) -> str:
    """Create a 5-axis radar (spider) chart for sub-component scores."""
    categories = list(SUB_COMPONENT_WEIGHTS.keys())
    labels = {
        "solidez": "Solidez\nFinanciera",
        "calidad": "Calidad\nde Activos",
        "eficiencia": "Eficiencia\ny Rentab.",
        "liquidez": "Liquidez",
        "diversificacion": "Diversi-\nficación",
    }

    values = [sub_scores.get(cat, 0) for cat in categories]
    values.append(values[0])  # close polygon

    angles = np.linspace(0, 2 * np.pi, len(categories), endpoint=False).tolist()
    angles.append(angles[0])

    fig, ax = plt.subplots(figsize=(10, 10), subplot_kw=dict(polar=True))
    ax.fill(angles, values, color=brand.ACCENT, alpha=0.25)
    ax.plot(angles, values, color=brand.ACCENT, linewidth=2)
    ax.scatter(angles[:-1], values[:-1], color=brand.ACCENT, s=80, zorder=5)

    ax.set_ylim(0, 100)
    ax.set_yticks([20, 40, 60, 80, 100])
    ax.set_yticklabels(["20", "40", "60", "80", "100"], fontsize=8, color=brand.MUTED)
    ax.set_xticks(angles[:-1])
    ax.set_xticklabels(
        [labels.get(c, c) for c in categories], fontsize=11,
    )
    ax.set_title(
        "Perfil de Riesgo — Sub-componentes",
        fontsize=14, pad=20, color=brand.INK,
    )

    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    fig.savefig(output_path, dpi=300, bbox_inches="tight", facecolor="white")
    plt.close(fig)
    return output_path


# ── PDF building blocks ───────────────────────────────────────────
# La portada y el chrome de página (banda navy + logo Arco + encabezado + nº de página +
# watermark) los provee el shell de marca compartido (shared.products.render.build_branded_pdf);
# este módulo solo arma el CUERPO (radar + tablas + narrativa) y la calificación va como headline.

def _build_sub_scores_table(sub_scores: Dict[str, float], styles,
                            entity_type: Optional[str] = None) -> List:
    """Tabla de sub-componentes con los pesos DEL TIPO DE ENTIDAD.

    Iteraba `SUB_COMPONENT_WEIGHTS` —la constante base, que es la de Banca Múltiple— para
    TODAS las entidades. Cinco de los seis tipos tienen perfil propio, así que la tabla salía
    mal en 75 de las 92 entidades calificadas, y contradecía el número de portada del propio
    informe: en un Insight real de una asociación de ahorros y préstamos (Bonao, 2025-12) la
    tabla decía 40/30/15/10/5 —que dan un score global de 60.07— mientras la portada mostraba
    61.24, que es lo que dan los pesos reales de una AAP (38/34/13/10/5). La narrativa, que sí
    recibe los pesos del tipo, decía 38% y 34%: el texto tenía razón y la tabla mentía.

    El motor de scoring nunca estuvo mal —`run_scoring` usa `get_sub_component_weights`—; el
    defecto era de las superficies que lo MUESTRAN.
    """
    elements: List = []
    elements.append(Paragraph("Sub-componentes", styles["SDQHeading"]))

    from modules.banking_score.scoring.weights import get_sub_component_weights
    pesos = get_sub_component_weights(entity_type)

    rows = [["Sub-componente", "Peso", "Score"]]
    for key, weight in pesos.items():
        score = sub_scores.get(key, 0)
        rows.append([
            SUB_COMPONENT_LABELS.get(key, key),
            f"{weight * 100:.0f}%",
            f"{score:.1f}",
        ])

    table = _branded_table(rows, [2.5 * inch, 1.0 * inch, 1.0 * inch], styles,
                           font_size=10, padding=6)
    elements.append(table)
    return elements


def _trend_arrow(series: Optional[List[Dict]]) -> str:
    """Flecha + delta del score entre el primer y último punto de la serie (Fase 4)."""
    if not series or len(series) < 2:
        return "—"
    first = series[0].get("score")
    last = series[-1].get("score")
    if first is None or last is None:
        return "—"
    delta = last - first
    arrow = "▲" if delta > 0.5 else ("▼" if delta < -0.5 else "=")
    return f"{arrow} {delta:+.0f}"


#: Decimales con que se imprime el valor de un indicador, por unidad. Un HHI con cuatro
#: decimales ("2091.6781") no informa más que "2,092": la precisión sobrante lee como ruido
#: en un documento de calificación.
_DECIMALES_POR_UNIDAD = {"%": 2, "índice": 0}


def _rotulo_y_valor(clave: str, crudo) -> tuple:
    """Etiqueta legible y valor CON SU UNIDAD, tomados del registro de indicadores.

    Sin esto la tabla salía con el fallback ``clave.replace("_", " ").title()`` —"Hhi
    Sectorial", "Pct Cartera A", "Roa", "Cost To Income"— y el valor crudo sin unidad y con
    todos sus decimales ("49.3813"). Es el MISMO fallback que este archivo ya documenta como
    "bug real detectado en producción" para los títulos de sección: se corrigió allá y quedó
    vivo acá, en la tabla que el comité mira primero.

    El registro (`INDICATOR_META`) ya tenía `label` y `unit` para los 20 indicadores; solo
    faltaba leerlos.
    """
    try:
        from modules.banking_score.scoring.indicator_detail import INDICATOR_META
        meta = INDICATOR_META.get(clave) or {}
    except Exception:  # noqa: BLE001 — el informe nunca se cae por el rótulo
        meta = {}
    rotulo = str(meta.get("label") or clave.replace("_", " ").title())
    unidad = meta.get("unit") or ""
    if crudo is None:
        return rotulo, "N/D"
    try:
        v = float(crudo)
    except (TypeError, ValueError):
        return rotulo, str(crudo)
    dec = _DECIMALES_POR_UNIDAD.get(unidad, 2)
    texto = f"{v:,.{dec}f}"
    if unidad == "%":
        texto += "%"
    return rotulo, texto


def _build_indicators_table(indicators: Dict[str, Dict], styles,
                            percentiles: Optional[Dict] = None,
                            trajectories: Optional[Dict] = None) -> List:
    elements: List = []
    elements.append(Paragraph("Indicadores Financieros", styles["SDQHeading"]))

    # Columnas de amplitud (Fase 4): percentil vs el sistema y tendencia del score,
    # opt-in — solo si el snapshot trajo los datos (deep dive de entidad real).
    pct_ind = (percentiles or {}).get("indicators") or {}
    traj_ind = (trajectories or {}).get("indicators") or {}
    has_amplitude = bool(pct_ind or traj_ind)

    header = ["Indicador", "Valor", "Score"]
    if has_amplitude:
        header += ["Percentil sist.", "Tendencia"]
    rows = [header]
    for name, data in indicators.items():
        if not isinstance(data, dict):
            continue
        rotulo, valor = _rotulo_y_valor(name, data.get("raw"))
        row = [rotulo, valor, f"{data.get('score', 0):.1f}"]
        if has_amplitude:
            sector = (pct_ind.get(name) or {}).get("sector") or {}
            p = sector.get("percentile")
            row.append(f"p{p:.0f}" if isinstance(p, (int, float)) else "—")
            row.append(_trend_arrow(traj_ind.get(name)))
        rows.append(row)

    if len(rows) > 1:
        col_widths = ([2.3 * inch, 1.1 * inch, 0.8 * inch, 1.2 * inch, 1.1 * inch]
                      if has_amplitude else [2.5 * inch, 1.5 * inch, 1.0 * inch])
        table = _branded_table(rows, col_widths, styles, font_size=9)
        elements.append(table)
        if has_amplitude:
            elements.append(Spacer(1, 0.08 * inch))
            elements.append(Paragraph(
                "Percentil sist. = posición del score del indicador vs todas las entidades "
                "calificadas en el período (p50 = mediana). Tendencia = variación del score "
                "entre el primer y el último trimestre disponible.", styles["SDQSmall"]))

    return elements


def _build_trajectory_table(trajectories: Dict, styles) -> List:
    """Trayectoria multi-período del score global + sub-componentes (Fase 4).

    Muestra la VENTANA COMPLETA que recibe la narrativa (``entity_trajectories(n=8)``).
    Antes recortaba a los últimos 6 cortes mientras el contexto del modelo llevaba 8, y las
    dos secciones que anclan la trayectoria citaban puntos que NO estaban en la página: la
    §1 el pico (74.81 de junio-24) y la §9 el inicio de ventana (74.30 de marzo-24). Ambas
    cifras eran correctas y ninguna verificable por el lector — el defecto que reportó el
    cliente el 2026-08-13. Si la narrativa razona sobre ocho cortes, se imprimen ocho.

    Dos decimales por el mismo hallazgo: a un decimal el 74.32 de septiembre-24 y el 74.30
    de marzo-24 se imprimen ambos "74.3", así que quien intenta casar la prosa con la tabla
    concluye que la sección se equivocó de período. El redondeo fabricaba la contradicción.
    """
    overall = trajectories.get("overall") or []
    sub = trajectories.get("sub") or {}
    if len(overall) < 2:
        return []

    periods = [p["period_end"] for p in overall][-TRAJECTORY_COLUMNS:]
    # Encabezado: períodos abreviados a YYYY-MM.
    short = [pe[:7] for pe in periods]
    elements: List = [Paragraph("Trayectoria del Score (multi-período)", styles["SDQHeading"])]

    def _series_row(label: str, series: List[Dict], bold: bool = False) -> List:
        by_period = {p["period_end"]: p.get("score") for p in series}
        # "Score global" va en negrita (fila resumen); como la fábrica envuelve cada
        # celda en un Paragraph, la negrita se aplica en la celda, no vía TableStyle.
        head = (Paragraph(_md_inline(label), styles["SDQTableCellBold"]) if bold else label)
        cells: List = [head]
        for pe in periods:
            v = by_period.get(pe)
            cells.append(f"{v:.2f}" if isinstance(v, (int, float)) else "—")
        return cells

    rows = [["Eje"] + short]
    rows.append(_series_row("Score global", overall, bold=True))
    for sk in ("solidez", "calidad", "eficiencia", "liquidez", "diversificacion"):
        if sub.get(sk):
            rows.append(_series_row(SUB_COMPONENT_LABELS.get(sk, sk), sub[sk]))

    # Con la ventana completa (8 cortes × 2 decimales) la tabla necesita más ancho útil y
    # menos cuerpo: se estrecha la columna de etiquetas y baja el tipo. Sin esto las celdas
    # envuelven y la tabla —que existe para que el lector VERIFIQUE— se vuelve ilegible.
    ancha = len(periods) > 6
    table = _branded_table(
        rows,
        [(1.55 if ancha else 1.9) * inch]
        + [((4.95 if ancha else 4.6) * inch) / len(periods)] * len(periods),
        styles, font_size=7.0 if ancha else 8.5, padding=3 if ancha else 4)
    elements.append(table)
    elements.append(Spacer(1, 0.08 * inch))
    elements.append(Paragraph(
        "Score 0–100 por eje en cada cierre trimestral. Permite leer la dirección del "
        "perfil (mejora/deterioro) más allá del corte vigente.", styles["SDQSmall"]))
    return elements


# ── Markdown → ReportLab renderer ─────────────────────────────────
# The AI narratives are Markdown (headings, **bold**, GFM tables, lists, ---).
# Render them as proper flowables instead of dumping raw markup into the PDF.

# Strip non-rendering glyphs the model sometimes emits (■ ✅ 🔴 emoji…), which
# otherwise show as tofu boxes in the base ReportLab fonts.
_GLYPH_RE = re.compile(
    "[▀-▟■-◿✀-➿☀-⛿\U0001f000-\U0001ffff️]"
)



def _md_inline(text: str) -> str:
    """Escape XML + **negrita** / *cursiva* (anidada) para un Paragraph de ReportLab.

    La implementación vive en `shared.products.render`: nació acá, pero el renderer compartido
    tenía el mismo defecto sin arreglar y dos copias del mismo criterio divergen. Se delega.
    """
    from shared.products.render import _inline

    return _inline(text)


def _md_split_row(line: str) -> List[str]:
    t = line.strip().strip("|")
    return [c.strip() for c in t.split("|")]


def _md_is_sep(line: str) -> bool:
    t = line.strip()
    return "-" in t and "|" in t and all(re.fullmatch(r":?-{1,}:?", c) for c in _md_split_row(t))


def _md_table(header: List[str], rows: List[List[str]], styles) -> Table:
    data = [[Paragraph(_md_inline(c), styles["SDQTableHead"]) for c in header]]
    for r in rows:
        cells = (r + [""] * len(header))[: len(header)]
        data.append([Paragraph(_md_inline(c), styles["SDQTableCell"]) for c in cells])
    ncol = len(header)
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


def _pull_quote(text: str, styles) -> Table:
    """Pull-quote de marca: texto navy con barra de acento signal-red a la izquierda."""
    t = Table([["", Paragraph(_md_inline(text), styles["SDQPullQuote"])]],
              colWidths=[0.09 * inch, 6.4 * inch])
    t.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (0, 0), ACCENT),
        ("LEFTPADDING", (1, 0), (1, 0), 10), ("TOPPADDING", (0, 0), (-1, -1), 6),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 6), ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
    ]))
    return t


def _md_to_flowables(text: str, styles) -> List:
    """Convert a Markdown string into ReportLab flowables."""
    out: List = []
    lines = text.replace("\r", "").split("\n")
    i = 0
    while i < len(lines):
        raw = lines[i]
        line = raw.strip()
        if not line:
            i += 1
            continue
        # Blockquote '> ' → pull-quote de marca (estándar de reporte).
        if line.startswith(">"):
            out.append(_pull_quote(line.lstrip(">").strip(), styles))
            out.append(Spacer(1, 0.08 * inch))
            i += 1
            continue
        # GFM table: header row + separator row
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
            lvl = len(h.group(1))
            style = styles["SDQSubHeading"] if lvl <= 2 else styles["SDQBodyBold"]
            out.append(Paragraph(_md_inline(h.group(2)), style))
            i += 1
            continue
        m = re.match(r"^(?:[-*]|\d+[.)])\s+(.*)$", line)
        if m:
            out.append(Paragraph("•&nbsp; " + _md_inline(m.group(1)), styles["SDQBullet"]))
            i += 1
            continue
        # Plain paragraph — gather following non-blank, non-special lines.
        buf = [line]
        i += 1
        while i < len(lines) and lines[i].strip() and not re.match(
            r"^(#{1,3}\s|[-*]\s|\d+[.)]\s|-{3,}$)", lines[i].strip()
        ) and "|" not in lines[i]:
            buf.append(lines[i].strip())
            i += 1
        out.append(Paragraph(_md_inline(" ".join(buf)), styles["SDQBody"]))
    return out


def _build_aportes_table(trajectories: Dict, entity_type: Optional[str], styles) -> List:
    """QUÉ MOVIÓ el score, en la página — no solo en la prosa.

    La descomposición ya viaja al modelo (`derived.aportes_al_cambio`), pero si no se imprime,
    la afirmación «el deterioro lo impulsó X» le queda al lector como un acto de fe. Es la
    misma lección que la tabla de trayectoria documenta arriba: si la narrativa razona sobre
    una cifra, esa cifra tiene que estar en la página.

    Y acá la verificación es especialmente barata: **cada columna SUMA el cambio total**. El
    lector puede comprobar la atribución con la mesa, que es exactamente lo que no pudo hacer
    con el informe donde la §1 adjudicó a la eficiencia un semestre en el que la eficiencia
    había mejorado.

    Se imprimen las ventanas que la serie soporta; con menos de dos cortes, nada.
    """
    from shared.narrative.derived import aportes_al_cambio
    from modules.banking_score.scoring.weights import get_sub_component_weights

    sub = trajectories.get("sub") or {}
    if not sub:
        return []
    ventanas = aportes_al_cambio(sub, get_sub_component_weights(entity_type))
    if not ventanas:
        return []

    elements: List = [Paragraph("Qué movió el score", styles["SDQHeading"])]
    cols = [v["ventana"].replace("el último ", "").capitalize() for v in ventanas]
    rows = [["Sub-componente"] + cols]
    for key in SUB_COMPONENT_LABELS:
        fila = [SUB_COMPONENT_LABELS[key]]
        visto = False
        for v in ventanas:
            ap = next((a for a in v["aportes"] if a["componente"] == key), None)
            fila.append(f"{ap['aporte_al_cambio']:+.2f}" if ap else "—")
            visto = visto or ap is not None
        if visto:
            rows.append(fila)
    if len(rows) == 1:
        return []
    rows.append([Paragraph("<b>Cambio total</b>", styles["SDQTableCellBold"])]
                + [Paragraph(f"<b>{v['cambio_total']:+.2f}</b>", styles["SDQTableCellBold"])
                   for v in ventanas])

    ancho = [2.5 * inch] + [1.15 * inch] * len(cols)
    elements.append(_branded_table(rows, ancho, styles, font_size=9.5, padding=5))
    elements.append(Spacer(1, 0.08 * inch))
    elements.append(Paragraph(
        "Aporte = variación del score del sub-componente × su peso. Cada columna SUMA el "
        "cambio total del período, de modo que la atribución es verificable contra esta "
        "tabla: la dimensión que más se mueve no es necesariamente la que más mueve el "
        "resultado.", styles["SDQSmall"]))
    return elements


def _build_banda_del_periodo(trajectories: Dict, styles) -> List:
    """Una línea: en qué banda abrió y cerró la ventana, y si cambió.

    El cambio de banda es el hecho que un comité recuerda del año, y hasta ahora había que
    deducirlo comparando la portada con la tabla de trayectoria. En 2025, 18 de 86 entidades
    del panel cambiaron de banda.
    """
    overall = trajectories.get("overall") or []
    if len(overall) < 2:
        return []
    ini, fin = overall[0], overall[-1]
    b0, b1 = ini.get("banda_resiliencia"), fin.get("banda_resiliencia")
    if not b0 or not b1:
        return []
    lapso = f"{ini['period_end'][:7]} → {fin['period_end'][:7]}"
    texto = (f"Banda de resiliencia en la ventana ({lapso}): <b>{b0}</b> → <b>{b1}</b>"
             + ("" if b0 == b1 else " — <b>cambió de banda en el período</b>"))
    return [Paragraph(texto, styles["SDQSmall"]), Spacer(1, 0.12 * inch)]


def _build_anuario_tables(anuario: Dict, styles) -> List:
    """Las tablas del ANUARIO: el año del sistema, por tipo y los cambios de banda.

    Todas las cifras vienen computadas (`reports/anuario`). Se imprimen porque un anuario que
    afirma «la banca múltiple se deterioró» sin la tabla al lado es una opinión: con ella, es
    una lectura que el lector audita.

    La MEDIANA es el titular y la media va al lado. Cuando divergen —caso real de 2025: la
    media sube y la mediana baja— la nota lo dice, porque titular con la media estaría
    técnicamente respaldado y sería falso como lectura.
    """
    if not anuario:
        return []
    elements: List = []
    sis = anuario.get("sistema") or {}

    por_corte = sis.get("por_corte") or []
    if por_corte:
        elements.append(Paragraph(f"El sistema en {anuario.get('anio', '')}",
                                  styles["SDQHeading"]))
        rows = [["Corte", "Mediana", "Media", "n"]]
        rows += [[c["corte"][:7], f"{c['mediana']:.2f}", f"{c['media']:.2f}", str(c["n"])]
                 for c in por_corte]
        elements.append(_branded_table(rows, [1.6 * inch, 1.2 * inch, 1.2 * inch, 0.8 * inch],
                                       styles, font_size=9.5, padding=5))
        nota = ("Mediana = la lectura del sistema; la media se muestra al lado por "
                "transparencia.")
        if sis.get("medias_y_medianas_divergen"):
            nota += (" <b>En este período media y mediana se mueven en sentidos opuestos</b>: "
                     "a la media la levantan unos pocos extremos, así que el año se lee por la "
                     "mediana.")
        elements.append(Spacer(1, 0.08 * inch))
        elements.append(Paragraph(nota, styles["SDQSmall"]))
        elements.append(Spacer(1, 0.25 * inch))

    tipos = anuario.get("por_tipo") or []
    if tipos:
        elements.append(Paragraph("Cambio del año por tipo de entidad", styles["SDQHeading"]))
        rows = [["Tipo de entidad", "Entidades", "Cambio mediano", "Lectura"]]
        rows += [[_TIPO_LABEL.get(t["tipo"], t["tipo"]), str(t["n"]),
                  f"{t['cambio_mediana']:+.2f}", t["direccion"]] for t in tipos]
        elements.append(_branded_table(rows, [2.1 * inch, 0.9 * inch, 1.3 * inch, 1.1 * inch],
                                       styles, font_size=9.5, padding=5))
        elements.append(Spacer(1, 0.25 * inch))

    bandas = anuario.get("cambios_de_banda") or []
    if bandas:
        elements.append(Paragraph("Entidades que cambiaron de banda", styles["SDQHeading"]))
        rows = [["Entidad", "Desde", "Hasta", "Δ Score"]]
        rows += [[b["entidad"], str(b["desde"]), str(b["hasta"]),
                  f"{b['cambio_score']:+.2f}"] for b in bandas]
        elements.append(_branded_table(rows, [2.5 * inch, 1.1 * inch, 1.1 * inch, 0.8 * inch],
                                       styles, font_size=9, padding=4))
        elements.append(Spacer(1, 0.25 * inch))

    uni = anuario.get("universo") or {}
    if uni:
        # El universo se DECLARA y las parciales se NOMBRAN. Ocultarlas sería peor que
        # excluirlas: desaparecerían sin aviso.
        texto = (f"Universo: {uni.get('comparables')} entidades con todos los cortes del año "
                 f"(de {uni.get('vistas_en_el_anio')} vistas). Los agregados y el orden se "
                 "computan solo sobre ellas.")
        parc = uni.get("parciales") or []
        if parc:
            detalle = "; ".join(f"{x['entidad']} ({x['cortes_presentes']}/{x['de']})"
                                for x in parc)
            texto += (f" Quedan fuera del orden, por año incompleto: {detalle}. No se ocultan: "
                      "un año parcial no se rankea contra uno completo.")
        elements.append(Paragraph(texto, styles["SDQSmall"]))
        elements.append(Spacer(1, 0.2 * inch))
    return elements


def _build_narrative_sections(narratives: Dict[str, str], styles) -> List:
    elements: List = []
    n = 0
    for section_key, text in narratives.items():
        title = NARRATIVE_SECTION_TITLES.get(
            section_key, section_key.replace("_", " ").title(),
        )
        n += 1
        elements.append(Paragraph(f"{n}. {title}", styles["SDQHeading"]))
        elements.extend(_md_to_flowables(text or "", styles))
        elements.append(Spacer(1, 0.2 * inch))
    return elements


def _build_disclaimer(styles) -> List:
    elements: List = []
    elements.append(Spacer(1, 0.5 * inch))
    elements.append(Paragraph("Disclaimer", styles["SDQSubHeading"]))
    elements.append(Paragraph(DISCLAIMER_ES, styles["SDQSmall"]))
    return elements


# ── Tier building blocks (Pulse band table · peer block) ──────────
# Opt-in: solo se renderizan cuando el ensamblador de nivel pasa el dato. No alteran
# el comportamiento de los 7 reportes base (que no los pasan).

def _build_band_distribution_table(band_distribution: Dict[str, int], styles) -> List:
    """Tabla de distribución del sistema por banda (Pulse — SIN nombres de entidad)."""
    elements: List = [Paragraph("Distribución del Sistema por Banda", styles["SDQHeading"])]
    total = sum(int(v) for v in band_distribution.values()) or 1
    rows = [["Banda", "Entidades", "% del sistema"]]
    for band, count in band_distribution.items():
        rows.append([str(band), str(int(count)), f"{int(count) / total * 100:.1f}%"])
    table = _branded_table(rows, [2.8 * inch, 1.4 * inch, 1.6 * inch], styles,
                           font_size=10, padding=6)
    elements.append(table)
    return elements


def _build_peer_block(peer_block: Dict, styles) -> List:
    """Posición competitiva del sistema (CR5/CR10/HHI). Para Insight/Deep Dive."""
    label = peer_block.get("metric_label", "Activos")
    elements: List = [Paragraph(f"Estructura de Mercado — {label}", styles["SDQHeading"])]
    rows = [["Métrica", "Valor"]]
    spec = [("CR5 (5 mayores)", "cr5", "%"), ("CR10 (10 mayores)", "cr10", "%"),
            ("HHI (concentración)", "hhi", "")]
    for disp, key, suffix in spec:
        val = peer_block.get(key)
        if val is not None:
            rows.append([disp, f"{val}{suffix}"])
    if len(rows) == 1:
        return []
    table = _branded_table(rows, [3.5 * inch, 2.0 * inch], styles,
                           font_size=9.5, padding=5)
    elements.append(table)
    return elements


_TIPO_LABEL = {
    "banca_multiple": "Banca múltiple", "aap": "Asociaciones de ahorros y préstamos",
    "banco_ahorro_credito": "Bancos de ahorro y crédito",
    "corporacion_credito": "Corporaciones de crédito", "cambiaria": "Agentes de cambio",
    "fiduciaria": "Fiduciarias",
}

_MACRO_DIR_LABEL = {"favorable": "Favorable", "adverso": "Adverso", "neutral": "Neutral"}


def _build_macro_table(entorno_macro: Dict, styles) -> List:
    """Tabla de factores del Entorno Operativo (macro BCRD, Fase 4). Opt-in: vacío si
    el snapshot no trajo factores (sin contrato macro)."""
    factors = (entorno_macro or {}).get("factors") or []
    if not factors:
        return []
    period = entorno_macro.get("period")
    ttl = "Entorno Operativo — Factores Macro (BCRD)" + (f" · {period}" if period else "")
    elements: List = [Paragraph(ttl, styles["SDQHeading"])]
    rows = [["Factor", "Valor", "Señal", "Lectura"]]
    for f in factors:
        val = f.get("value")
        unit = f.get("unit") or ""
        val_str = (f"{val:g}{unit}" if isinstance(val, (int, float)) else "N/D")
        rows.append([
            f.get("label", f.get("key", "")),
            val_str,
            _MACRO_DIR_LABEL.get(f.get("direction"), "—"),
            Paragraph(_md_inline(f.get("reading", "") or ""), styles["SDQSmall"]),
        ])
    table = _branded_table(
        rows, [1.7 * inch, 1.0 * inch, 0.9 * inch, 2.9 * inch], styles,
        aligns=["LEFT", "CENTER", "CENTER", "LEFT"])
    elements.append(table)
    elements.append(Spacer(1, 0.08 * inch))
    elements.append(Paragraph(
        "Telón macroeconómico sistémico (BCRD), común a todas las entidades. No forma parte "
        "de la calificación standalone; encuadra la dirección del entorno operativo.",
        styles["SDQSmall"]))
    return elements


def _sensitivity_rows(rows: List[Dict]) -> List[List]:
    out: List[List] = []
    for r in rows:
        delta = r.get("delta_overall", 0)
        out.append([
            r.get("label", r.get("indicador", "")),
            f"{r.get('raw_actual', '')}",
            r.get("umbral_fmt", ""),
            str(r.get("banda_objetivo", "")).capitalize(),
            f"{delta:+.1f}",
        ])
    return out


def _build_sensitivity_table(sens: Dict, styles) -> List:
    """Tabla de sensibilidades simétrica (Fase 4): palancas al alza / riesgos a la baja,
    con umbral en valor crudo e impacto en el score global. Opt-in (Deep Dive)."""
    up = sens.get("palancas_alza") or []
    down = sens.get("riesgos_baja") or []
    if not up and not down:
        return []
    elements: List = [Paragraph("Sensibilidad del Score — Palancas y Riesgos", styles["SDQHeading"])]
    header = ["Indicador", "Actual", "Umbral", "Banda→", "Δ Score"]
    col_widths = [2.2 * inch, 0.9 * inch, 1.1 * inch, 1.1 * inch, 0.9 * inch]

    def _block(subtitle: str, rows: List[List]):
        if not rows:
            return
        elements.append(Paragraph(subtitle, styles["SDQSubHeading"]))
        table = _branded_table([header] + rows, col_widths, styles)
        elements.append(table)
        elements.append(Spacer(1, 0.12 * inch))

    _block("Palancas al alza — mejorar a este umbral sube el score", _sensitivity_rows(up))
    _block("Riesgos a la baja — deteriorarse a este umbral hace perder banda", _sensitivity_rows(down))
    elements.append(Paragraph(
        "Umbral = valor crudo del indicador que lleva su score a la frontera de banda "
        "indicada; Δ Score = cambio resultante en el score global (recomputado con la "
        "metodología, pesos por tipo de entidad).",
        styles["SDQSmall"]))
    return elements


def _build_support_table(support: Dict, styles) -> List:
    """Tabla de Soporte y Techo Soberano (Fase 6): standalone vs contexto estructural.
    Opt-in (Deep Dive). CONTEXTO — no muta el score standalone."""
    if not support:
        return []
    sysd = support.get("systemic") or {}
    sov = support.get("sovereign") or {}
    standalone = support.get("standalone") or {}
    elements: List = [Paragraph("Soporte y Techo Soberano — Contexto Estructural", styles["SDQHeading"])]

    def _pct(v):
        return f"{v:.2f}%" if isinstance(v, (int, float)) else "—"

    # La columna "Lectura" trae texto largo y dinámico (techo soberano, panel multi-agencia):
    # va en un Paragraph para que ReportLab haga wrap dentro del ancho de columna (un str plano
    # NO envuelve y se desborda). _md_inline escapa el XML (p.ej. "S&P" → "S&amp;P").
    def _val(txt):
        return Paragraph(_md_inline(str(txt)), styles["SDQTableCell"])

    rows = [["Eje", "Lectura"]]
    rows.append(["Fortaleza standalone (SDQ)",
                 _val(f"{standalone.get('tier', '—')} · {standalone.get('score', '—')}/100")])
    rows.append(["Propiedad estatal", _val("Sí" if support.get("state_owned") else "No")])
    rows.append(["Importancia sistémica", _val(sysd.get("label") or "—")])
    rows.append(["Cuota de activos / depósitos",
                 _val(f"{_pct(sysd.get('activos_share'))} · {_pct(sysd.get('depositos_share'))}")])
    sov_txt = "—"
    if sov.get("rating"):
        outlook = f", {sov.get('outlook')}" if sov.get("outlook") else ""
        sov_txt = (f"{sov.get('rating')} ({sov.get('agency')}{outlook}; última acción "
                   f"{sov.get('as_of')}) · {sov.get('score')}/100")
        if sov.get("affirm_date"):
            sov_txt += f" · afirmado {sov.get('affirm_date')}"
    rows.append(["Techo soberano (RD) — ancla", _val(sov_txt)])
    # Panel multi-agencia: contexto de convergencia/divergencia (S&P ancla el índice;
    # Fitch/Moody's no lo mueven — política "S&P manda").
    agencies = sov.get("agencies") or []
    if len(agencies) > 1:
        def _ag(a):
            ol = f", {a.get('outlook')}" if a.get("outlook") else ""
            return f"{a.get('name')} {a.get('rating')}{ol} ({a.get('action_date') or 's/f'})"
        rows.append(["Panel multi-agencia", _val(" · ".join(_ag(a) for a in agencies))])
    table = _branded_table(rows, [2.3 * inch, 4.2 * inch], styles,
                           aligns=["LEFT", "LEFT"])
    elements.append(table)
    elements.append(Spacer(1, 0.08 * inch))
    elements.append(Paragraph(
        "Capa de CONTEXTO estilo Fitch (VR/GSR/IDR): el soporte estatal, la importancia "
        "sistémica y el techo soberano NO forman parte de la calificación SDQ standalone "
        "(que mide fortaleza relativa dentro de RD, no riesgo de crédito absoluto). El techo "
        "soberano se ancla en la calificación de S&amp;P (última acción); Fitch y Moody's se "
        "muestran como contexto de convergencia y no mueven la lectura.", styles["SDQSmall"]))
    return elements


def _order_narratives(narratives: Dict[str, str],
                      sections: Optional[List[str]]) -> Dict[str, str]:
    """Filtra/ordena las narrativas por `sections` (manifiesto del nivel).

    Default (`sections=None`) = comportamiento actual: las narrativas tal cual.
    """
    if not sections:
        return narratives
    ordered = {s: narratives[s] for s in sections if s in narratives}
    # Preserva cualquier sección extra no listada (no perder contenido inadvertidamente).
    for k, v in narratives.items():
        ordered.setdefault(k, v)
    return ordered


# ── Public API ────────────────────────────────────────────────────

async def generate_pdf_report(
    report_type: str,
    bank_name: str,
    scoring_result: Dict,
    period: str,
    narratives: Optional[Dict[str, str]] = None,
    output_dir: Optional[str] = None,
    *,
    sections: Optional[List[str]] = None,
    tier: Optional[str] = None,
    watermark: Optional[str] = None,
    sample: bool = False,
    band_distribution: Optional[Dict[str, int]] = None,
    peer_block: Optional[Dict] = None,
    anuario: Optional[Dict] = None,
) -> str:
    """Generate a branded PDF report and return the file path.

    Args:
        report_type: One of the 7 report type keys.
        bank_name: Display name of the bank (or system label for Pulse).
        scoring_result: Output from ``run_scoring()`` or equivalent.
        period: Period string (e.g. ``"2024-Q4"``).
        narratives: ``{section_key: text}``. If ``None``, no narrative pages.
        output_dir: Override for ``settings.REPORTS_DIR``.

    Extensiones de productización (NO-ROTURA — defaults = comportamiento actual):
        sections: si viene, filtra/ordena las secciones narrativas (manifiesto del nivel).
        tier: nivel comercial (metadato del título). No altera la estructura por sí solo.
        watermark: pie de marca por nivel (p.ej. "Vista abierta · SDQMIP").
        sample: estampa "MUESTRA — DATA ILUSTRATIVA" en cada página.
        band_distribution: ``{banda: conteo}`` → tabla de sistema anonimizada (Pulse).
        peer_block: ``{metric_label, cr5, cr10, hhi}`` → estructura de mercado (Insight/DD).

    Returns:
        Absolute path to the generated PDF file.
    """
    output_dir = output_dir or settings.REPORTS_DIR
    os.makedirs(output_dir, exist_ok=True)

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    safe_name = bank_name.replace(" ", "_").lower()
    filename = f"{report_type}_{safe_name}_{timestamp}.pdf"
    filepath = os.path.join(output_dir, filename)

    styles = _get_styles()
    body: List = []

    overall_score = scoring_result.get("overall_score", 0)
    # Perfil SDQ: el titular lleva los DOS EJES. Antes llevaba `SDQ-AA+`, o sea que el
    # documento que se entrega al cliente encabezaba con la notación que el sistema retiró.
    banda_ejec = scoring_result.get("banda_ejecucion")
    banda_resil = scoring_result.get("banda_resiliencia")
    sub_scores = scoring_result.get("sub_components", {})
    indicators = scoring_result.get("indicators", {})

    # 1. Radar chart (for full_rating, scorecard, datawatch)
    if sub_scores and report_type in ("full_rating", "scorecard", "datawatch"):
        chart_dir = settings.CHARTS_DIR
        os.makedirs(chart_dir, exist_ok=True)
        chart_path = os.path.join(
            chart_dir, f"radar_{safe_name}_{timestamp}.png",
        )
        try:
            generate_radar_chart(sub_scores, chart_path)
            img = RLImage(chart_path, width=5 * inch, height=5 * inch)
            body.append(img)
            body.append(Spacer(1, 0.3 * inch))
        except Exception as e:
            logger.warning("Radar chart failed: %s", e)

    # 2. Sub-scores table
    if sub_scores:
        body.extend(_build_sub_scores_table(
            sub_scores, styles, scoring_result.get("entity_type")))
        body.append(Spacer(1, 0.3 * inch))

    # Amplitud (Fase 4): trayectoria multi-período + percentil vs el sistema. Vienen en
    # el scoring_result (calculados en snapshot); ausentes en Pulse/muestras → opt-in.
    trajectories = scoring_result.get("trayectorias") or {}
    percentiles = scoring_result.get("percentiles") or {}

    # 3. Indicators table (detailed reports only) — con columnas de percentil/tendencia.
    if indicators and report_type in ("full_rating", "scorecard", "datawatch"):
        body.extend(_build_indicators_table(indicators, styles, percentiles, trajectories))
        body.append(Spacer(1, 0.3 * inch))

    # 3a-bis. Trayectoria del score (multi-período) — solo si el snapshot la trajo.
    if trajectories.get("overall"):
        traj_els = _build_trajectory_table(trajectories, styles)
        if traj_els:
            body.extend(traj_els)
            body.extend(_build_banda_del_periodo(trajectories, styles))
            body.append(Spacer(1, 0.3 * inch))
        # Qué movió el score: la descomposición que la narrativa ya recibe, ahora también
        # impresa — sin ella la atribución le queda al lector como acto de fe.
        ap_els = _build_aportes_table(trajectories, scoring_result.get("entity_type"), styles)
        if ap_els:
            body.extend(ap_els)
            body.append(Spacer(1, 0.3 * inch))

    # 3a-ter. ANUARIO — las tablas del año del sistema. Van arriba porque son el SUJETO del
    # documento, no un anexo: el anuario no analiza una entidad, analiza el año.
    if anuario:
        body.extend(_build_anuario_tables(anuario, styles))

    # 3b. Pulse — distribución del sistema por banda (opt-in, anonimizado).
    if band_distribution:
        body.extend(_build_band_distribution_table(band_distribution, styles))
        body.append(Spacer(1, 0.3 * inch))

    # 3c. Bloque de pares — estructura de mercado (opt-in; Insight/Deep Dive).
    if peer_block:
        body.extend(_build_peer_block(peer_block, styles))
        body.append(Spacer(1, 0.3 * inch))

    # 3d. Entorno Operativo — factores macro BCRD (opt-in; Deep Dive con contrato macro).
    entorno_macro = scoring_result.get("entorno_macro")
    if entorno_macro:
        macro_els = _build_macro_table(entorno_macro, styles)
        if macro_els:
            body.extend(macro_els)
            body.append(Spacer(1, 0.3 * inch))

    # 3e. Sensibilidad del score — palancas al alza / riesgos a la baja (opt-in; Deep Dive).
    sensibilidades = scoring_result.get("sensibilidades")
    if sensibilidades:
        sens_els = _build_sensitivity_table(sensibilidades, styles)
        if sens_els:
            body.extend(sens_els)
            body.append(Spacer(1, 0.3 * inch))

    # 3f. Soporte y Techo Soberano — contexto estructural estilo Fitch (opt-in; Deep Dive).
    soporte = scoring_result.get("soporte_soberano")
    if soporte:
        sup_els = _build_support_table(soporte, styles)
        if sup_els:
            body.extend(sup_els)
            body.append(Spacer(1, 0.3 * inch))

    # 4. Narrative sections (filtradas/ordenadas por el manifiesto si `sections`). Un único
    # salto de página separa el bloque de datos (tablas) de la narrativa; las tablas fluyen
    # naturalmente entre sí (evita páginas en blanco cuando el detalle desborda la primera).
    if narratives:
        if body:
            body.append(PageBreak())
        body.extend(_build_narrative_sections(
            _order_narratives(narratives, sections), styles))

    # 5. Disclaimer (texto propio de banking; el shell no lo añade).
    body.extend(_build_disclaimer(styles))

    # Portada + chrome de marca compartidos (banda navy + logo Arco + encabezado corrido +
    # nº de página + watermark/estampa) vía el shell de render.py — la calificación va como
    # headline (pull-quote de portada), igual que los demás productos.
    title_label = REPORT_TYPE_LABELS.get(report_type, report_type)
    if tier:
        title_label = f"{title_label} · {TIER_LABELS.get(tier, tier)}"
    # Los dos ejes juntos o ninguno: un titular con solo uno sería el símbolo único otra vez.
    headline = None
    if banda_ejec and banda_resil:
        headline = f"Ejecución {banda_ejec} · Resiliencia {banda_resil}"
    elif overall_score:
        headline = f"{overall_score:.1f}/100"

    from shared.products.render import build_branded_pdf
    build_branded_pdf(
        path=filepath, title=title_label, display_name=bank_name, period=period,
        body=body, headline=headline, watermark=watermark, sample=sample,
        add_disclaimer=False)
    logger.info("PDF generated: %s", filepath)
    return filepath
