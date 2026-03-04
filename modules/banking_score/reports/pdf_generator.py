"""PDF report generation using ReportLab.

Produces branded SDQ Market Intelligence PDFs for 7 report types:
full_rating, scorecard, communique, datawatch, wire, criteria, sector_outlook.

Extracted from financial-analysis-agent/backend/app/services/sdq_report_service.py.
"""
import logging
import os
from datetime import datetime
from typing import Dict, List, Optional

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
from reportlab.lib.colors import HexColor
from reportlab.lib.enums import TA_CENTER, TA_JUSTIFY
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import inch
from reportlab.platypus import (
    Image as RLImage,
    PageBreak,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)

from modules.banking_score.scoring.rating_scale import get_tier_color
from modules.banking_score.scoring.weights import SUB_COMPONENT_WEIGHTS
from shared.config.settings import settings

logger = logging.getLogger(__name__)

# ── Brand constants ───────────────────────────────────────────────
NAVY = HexColor("#1A365D")
BLUE = HexColor("#2B6CB0")
GREEN = HexColor("#38A169")
LIGHT_GRAY = HexColor("#F7FAFC")
GRAY = HexColor("#718096")
WHITE = HexColor("#FFFFFF")

MARGIN = 0.75 * inch

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
}

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
    "recommendation": "Recomendación",
    "trend_analysis": "Análisis de Tendencias",
    "sector_outlook": "Perspectiva Sectorial",
}


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
    return styles


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
    ax.fill(angles, values, color="#2B6CB0", alpha=0.25)
    ax.plot(angles, values, color="#2B6CB0", linewidth=2)
    ax.scatter(angles[:-1], values[:-1], color="#2B6CB0", s=80, zorder=5)

    ax.set_ylim(0, 100)
    ax.set_yticks([20, 40, 60, 80, 100])
    ax.set_yticklabels(["20", "40", "60", "80", "100"], fontsize=8, color="#718096")
    ax.set_xticks(angles[:-1])
    ax.set_xticklabels(
        [labels.get(c, c) for c in categories], fontsize=11,
    )
    ax.set_title(
        "Perfil de Riesgo — Sub-componentes",
        fontsize=14, pad=20, color="#1A365D",
    )

    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    fig.savefig(output_path, dpi=300, bbox_inches="tight", facecolor="white")
    plt.close(fig)
    return output_path


# ── PDF building blocks ───────────────────────────────────────────

def _build_cover_page(
    bank_name: str,
    rating_tier: str,
    overall_score: float,
    period: str,
    report_type: str,
    styles,
) -> List:
    elements: List = []
    elements.append(Spacer(1, 1.5 * inch))
    elements.append(Paragraph("SDQ Market Intelligence", styles["SDQTitle"]))
    elements.append(Spacer(1, 0.3 * inch))

    title = REPORT_TYPE_LABELS.get(report_type, "Informe")
    elements.append(Paragraph(title, styles["SDQHeading"]))
    elements.append(Spacer(1, 0.5 * inch))
    elements.append(Paragraph(bank_name, styles["SDQTitle"]))
    elements.append(Spacer(1, 0.3 * inch))

    tier_color = get_tier_color(rating_tier)
    tier_style = ParagraphStyle(
        "TierDisplay", fontSize=48,
        textColor=HexColor(tier_color), alignment=TA_CENTER, spaceAfter=10,
    )
    elements.append(Paragraph(rating_tier, tier_style))
    elements.append(Paragraph(
        f"Score: {overall_score:.1f}/100", styles["SDQSubHeading"],
    ))
    elements.append(Spacer(1, 0.5 * inch))
    elements.append(Paragraph(f"Período: {period}", styles["SDQBody"]))
    elements.append(Paragraph(
        f"Fecha: {datetime.now().strftime('%d/%m/%Y')}", styles["SDQBody"],
    ))
    elements.append(PageBreak())
    return elements


def _build_sub_scores_table(sub_scores: Dict[str, float], styles) -> List:
    elements: List = []
    elements.append(Paragraph("Sub-componentes", styles["SDQHeading"]))

    rows = [["Sub-componente", "Peso", "Score"]]
    for key, weight in SUB_COMPONENT_WEIGHTS.items():
        score = sub_scores.get(key, 0)
        rows.append([
            SUB_COMPONENT_LABELS.get(key, key),
            f"{weight * 100:.0f}%",
            f"{score:.1f}",
        ])

    table = Table(rows, colWidths=[2.5 * inch, 1.0 * inch, 1.0 * inch])
    table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), NAVY),
        ("TEXTCOLOR", (0, 0), (-1, 0), WHITE),
        ("FONTSIZE", (0, 0), (-1, -1), 10),
        ("ALIGN", (1, 0), (-1, -1), "CENTER"),
        ("GRID", (0, 0), (-1, -1), 0.5, GRAY),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [WHITE, LIGHT_GRAY]),
        ("TOPPADDING", (0, 0), (-1, -1), 6),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
    ]))
    elements.append(table)
    return elements


def _build_indicators_table(indicators: Dict[str, Dict], styles) -> List:
    elements: List = []
    elements.append(Paragraph("Indicadores Financieros", styles["SDQHeading"]))

    header = ["Indicador", "Valor", "Score"]
    rows = [header]
    for name, data in indicators.items():
        if isinstance(data, dict):
            rows.append([
                name.replace("_", " ").title(),
                f"{data.get('raw', 'N/A')}",
                f"{data.get('score', 0):.1f}",
            ])

    if len(rows) > 1:
        table = Table(rows, colWidths=[2.5 * inch, 1.5 * inch, 1.0 * inch])
        table.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), NAVY),
            ("TEXTCOLOR", (0, 0), (-1, 0), WHITE),
            ("FONTSIZE", (0, 0), (-1, -1), 9),
            ("ALIGN", (1, 0), (-1, -1), "CENTER"),
            ("GRID", (0, 0), (-1, -1), 0.5, GRAY),
            ("ROWBACKGROUNDS", (0, 1), (-1, -1), [WHITE, LIGHT_GRAY]),
            ("TOPPADDING", (0, 0), (-1, -1), 4),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
        ]))
        elements.append(table)

    return elements


def _build_narrative_sections(narratives: Dict[str, str], styles) -> List:
    elements: List = []
    for section_key, text in narratives.items():
        title = NARRATIVE_SECTION_TITLES.get(
            section_key, section_key.replace("_", " ").title(),
        )
        elements.append(Paragraph(title, styles["SDQSubHeading"]))
        for para in text.split("\n\n"):
            para = para.strip()
            if para:
                # Escape XML special characters for ReportLab
                safe = (
                    para.replace("&", "&amp;")
                    .replace("<", "&lt;")
                    .replace(">", "&gt;")
                )
                elements.append(Paragraph(safe, styles["SDQBody"]))
        elements.append(Spacer(1, 0.2 * inch))
    return elements


def _build_disclaimer(styles) -> List:
    elements: List = []
    elements.append(Spacer(1, 0.5 * inch))
    elements.append(Paragraph("Disclaimer", styles["SDQSubHeading"]))
    elements.append(Paragraph(DISCLAIMER_ES, styles["SDQSmall"]))
    return elements


# ── Public API ────────────────────────────────────────────────────

async def generate_pdf_report(
    report_type: str,
    bank_name: str,
    scoring_result: Dict,
    period: str,
    narratives: Optional[Dict[str, str]] = None,
    output_dir: Optional[str] = None,
) -> str:
    """Generate a branded PDF report and return the file path.

    Args:
        report_type: One of the 7 report type keys.
        bank_name: Display name of the bank.
        scoring_result: Output from ``run_scoring()`` or equivalent.
        period: Period string (e.g. ``"2024-Q4"``).
        narratives: ``{section_key: text}``. If ``None``, no narrative pages.
        output_dir: Override for ``settings.REPORTS_DIR``.

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
    elements: List = []

    overall_score = scoring_result.get("overall_score", 0)
    rating_tier = scoring_result.get("rating_tier", "N/A")
    sub_scores = scoring_result.get("sub_components", {})
    indicators = scoring_result.get("indicators", {})

    # 1. Cover page
    elements.extend(_build_cover_page(
        bank_name, rating_tier, overall_score, period, report_type, styles,
    ))

    # 2. Radar chart (for full_rating, scorecard, datawatch)
    if sub_scores and report_type in ("full_rating", "scorecard", "datawatch"):
        chart_dir = settings.CHARTS_DIR
        os.makedirs(chart_dir, exist_ok=True)
        chart_path = os.path.join(
            chart_dir, f"radar_{safe_name}_{timestamp}.png",
        )
        try:
            generate_radar_chart(sub_scores, chart_path)
            img = RLImage(chart_path, width=5 * inch, height=5 * inch)
            elements.append(img)
            elements.append(Spacer(1, 0.3 * inch))
        except Exception as e:
            logger.warning("Radar chart failed: %s", e)

    # 3. Sub-scores table
    if sub_scores:
        elements.extend(_build_sub_scores_table(sub_scores, styles))
        elements.append(Spacer(1, 0.3 * inch))

    # 4. Indicators table (detailed reports only)
    if indicators and report_type in ("full_rating", "scorecard", "datawatch"):
        elements.extend(_build_indicators_table(indicators, styles))
        elements.append(PageBreak())

    # 5. Narrative sections
    if narratives:
        elements.extend(_build_narrative_sections(narratives, styles))

    # 6. Disclaimer
    elements.extend(_build_disclaimer(styles))

    # Build PDF
    doc = SimpleDocTemplate(
        filepath,
        pagesize=A4,
        leftMargin=MARGIN,
        rightMargin=MARGIN,
        topMargin=MARGIN,
        bottomMargin=MARGIN,
        title=f"SDQ — {REPORT_TYPE_LABELS.get(report_type, report_type)} — {bank_name}",
        author="SDQ Market Intelligence",
    )
    doc.build(elements)
    logger.info("PDF generated: %s", filepath)
    return filepath
