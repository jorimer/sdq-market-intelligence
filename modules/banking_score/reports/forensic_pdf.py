"""Informe forense en PDF branded (reportlab + matplotlib).

Versión PDF del documento forense (la que el dueño pide al "informe completo"). Reusa los
helpers de ``pdf_generator`` (estilos SDQ, pull-quote, markdown→flowables, tabla branded) y
el patrón matplotlib del radar para los gráficos del dato real. Devuelve bytes.
"""
from __future__ import annotations

import os
import tempfile
from io import BytesIO
from typing import Dict, List, Optional

import matplotlib

matplotlib.use("Agg")  # sin display (servidor)
import matplotlib.pyplot as plt  # noqa: E402
from reportlab.lib.pagesizes import letter  # noqa: E402
from reportlab.lib.units import inch  # noqa: E402
from reportlab.platypus import (  # noqa: E402
    Image as RLImage,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
)

from modules.banking_score.reports.pdf_generator import (  # noqa: E402
    _branded_table,
    _get_styles,
    _md_to_flowables,
    _pull_quote,
)


def _nan(v):
    return float("nan") if v is None else v


def _chart_credito(series: List[Dict], path: str) -> None:
    xs = list(range(len(series)))
    mora = [_nan(p.get("morosidad_pct")) for p in series]
    cob = [_nan(p.get("cobertura_pct")) for p in series]
    fig, ax = plt.subplots(figsize=(9, 3.1))
    ax.plot(xs, mora, color="#C8392E", lw=2, label="Morosidad %")
    ax.plot(xs, cob, color="#0F7E7E", lw=2, label="Cobertura %")
    step = max(1, len(series) // 8)
    ax.set_xticks(xs[::step])
    ax.set_xticklabels([series[i]["fecha"][:7] for i in xs[::step]], fontsize=8, color="#76829C")
    ax.tick_params(axis="y", labelsize=8, colors="#76829C")
    ax.grid(True, color="#EAEFF6", lw=0.8)
    ax.spines[["top", "right"]].set_visible(False)
    ax.legend(fontsize=9, frameon=False, loc="upper left")
    fig.savefig(path, dpi=130, bbox_inches="tight")
    plt.close(fig)


def _chart_deposito(series: List[Dict], path: str) -> None:
    vals = [(i, float(p["dep_mom_pct"])) for i, p in enumerate(series)
            if p.get("dep_mom_pct") is not None]
    fig, ax = plt.subplots(figsize=(9, 2.4))
    xs = [i for i, _ in vals]
    ys = [v for _, v in vals]
    ax.bar(xs, ys, color=["#C8392E" if y < 0 else "#15875A" for y in ys], width=0.7)
    ax.axhline(0, color="#D6DEEC", lw=1)
    step = max(1, len(series) // 8)
    ax.set_xticks(list(range(0, len(series), step)))
    ax.set_xticklabels([series[i]["fecha"][:7] for i in range(0, len(series), step)],
                       fontsize=8, color="#76829C")
    ax.tick_params(axis="y", labelsize=8, colors="#76829C")
    ax.grid(True, axis="y", color="#EAEFF6", lw=0.8)
    ax.spines[["top", "right"]].set_visible(False)
    fig.savefig(path, dpi=130, bbox_inches="tight")
    plt.close(fig)


def render_forensic_pdf(pkg: Dict, narrative_md: str, *, degraded: bool = False) -> bytes:
    """Documento forense en PDF (bytes)."""
    from modules.banking_score.historical_service import forensic_narrative_context

    meta, bt, series = pkg["meta"], pkg["backtest"], pkg["series"]
    ctx = forensic_narrative_context(pkg)
    styles = _get_styles()
    story: List = []

    story.append(Paragraph("SDQ·MIP — Informe Forense · Retrospectivo", styles["SDQSmall"]))
    story.append(Paragraph(f"{meta['nombre']}", styles["SDQTitle"]))
    story.append(Paragraph("Anatomía de una quiebra · reconstrucción del deterioro sobre dato "
                           "mensual real", styles["SDQSubHeading"]))
    lead = bt.get("lead_months")
    verdict = (f"Deterioro detectable desde {bt.get('onset_cluster')} — {lead} meses antes del "
               f"colapso." if bt.get("onset_cluster") and lead is not None
               else "Los ratios reportados nunca formaron un cluster de alerta antes de la salida.")
    story.append(Spacer(1, 6))
    story.append(_pull_quote(verdict, styles))
    story.append(Spacer(1, 8))

    # Resumen (tabla branded de 4 cifras)
    stat_rows = [
        ["Inicio del deterioro", "Anticipación", "Morosidad máx.", "Meses en alerta"],
        [bt.get("onset_cluster") or "—",
         f"{lead} meses" if lead is not None else "—",
         f"{ctx['morosidad_maxima_pct']:.1f}%" if ctx.get("morosidad_maxima_pct") is not None else "—",
         f"{bt.get('n_high_months', 0)} de {meta['n_periodos']}"],
    ]
    story.append(_branded_table(stat_rows, [1.6 * inch, 1.5 * inch, 1.5 * inch, 1.6 * inch], styles))
    story.append(Spacer(1, 12))

    tmp = tempfile.mkdtemp(prefix="forensic_pdf_")
    try:
        c1, c2 = os.path.join(tmp, "credito.png"), os.path.join(tmp, "dep.png")
        _chart_credito(series, c1)
        _chart_deposito(series, c2)
        story.append(Paragraph("Riesgo de crédito y colchón de provisiones", styles["SDQSubHeading"]))
        story.append(RLImage(c1, width=6.5 * inch, height=6.5 * 3.1 / 9 * inch))
        story.append(Spacer(1, 8))
        story.append(Paragraph("Fuga de depósitos (variación intermensual)", styles["SDQSubHeading"]))
        story.append(RLImage(c2, width=6.5 * inch, height=6.5 * 2.4 / 9 * inch))
        story.append(Spacer(1, 12))

        story.append(Paragraph("Lectura forense", styles["SDQHeading"]))
        if narrative_md and not degraded:
            story.extend(_md_to_flowables(narrative_md, styles))
        else:
            story.append(Paragraph("La lectura narrativa no está disponible en este momento; los "
                                   "datos y el backtest de arriba son completos.", styles["SDQBody"]))
        story.append(Spacer(1, 10))

        story.append(Paragraph("Metodología y fuentes", styles["SDQHeading"]))
        story.append(Paragraph(
            "Todas las cifras salen del estado de situación y de resultados mensual por entidad "
            "publicado por la Superintendencia de Bancos (Cronología SB). El inicio del deterioro es "
            "el primer mes con un cluster de ≥2 alertas altas simultáneas.", styles["SDQBody"]))
        story.append(Paragraph(
            "Límite: el capital regulatorio Basilea no existe en el balance contable pre-2004 — el "
            "apalancamiento patrimonio/activos es un proxy etiquetado. Informe retrospectivo/forense, "
            "no una calificación emitida en su momento.", styles["SDQSmall"]))

        buf = BytesIO()
        doc = SimpleDocTemplate(buf, pagesize=letter, topMargin=0.7 * inch,
                                bottomMargin=0.7 * inch, leftMargin=0.75 * inch, rightMargin=0.75 * inch)
        doc.build(story)
        return buf.getvalue()
    finally:
        for f in (os.path.join(tmp, "credito.png"), os.path.join(tmp, "dep.png")):
            if os.path.exists(f):
                os.remove(f)
        os.rmdir(tmp)
