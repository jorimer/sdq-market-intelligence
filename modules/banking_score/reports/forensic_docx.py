"""Informe forense en Word (.docx) branded — paridad con el PDF forense.

Misma anatomía que ``render_forensic_pdf`` (título, veredicto, tabla-resumen, los dos
gráficos del dato real, lectura forense y metodología) pero **editable** por el cliente.
Reusa los gráficos matplotlib del PDF forense y los helpers de marca del renderer docx
genérico. Devuelve bytes.
"""
from __future__ import annotations

import os
import tempfile
from io import BytesIO
from typing import Dict

from docx import Document
from docx.shared import Inches

from modules.banking_score.reports.forensic_pdf import _chart_credito, _chart_deposito
from shared.products.render_docx import (
    DISCLAIMER_ES,
    _BLUE,
    _GRAY,
    _LOGO,
    _NAVY,
    _NAVY_HEX,
    _SIGNAL,
    _WHITE,
    _add_runs,
    _furniture,
    _left_accent,
    _md_body,
    _shade,
)


def render_forensic_docx(pkg: Dict, narrative_md: str, *, degraded: bool = False) -> bytes:
    """Documento forense en Word (bytes) — misma anatomía que el PDF, editable."""
    from modules.banking_score.historical_service import forensic_narrative_context

    meta, bt, series = pkg["meta"], pkg["backtest"], pkg["series"]
    ctx = forensic_narrative_context(pkg)

    doc = Document()
    _furniture(doc, f"SDQ·MIP — Informe Forense · {meta['nombre']}", None, False)

    # ── Cabecera de marca ──
    if os.path.exists(_LOGO):
        doc.add_picture(_LOGO, width=Inches(0.5))
    _add_runs(doc.add_paragraph(), "SDQ·MIP — INFORME FORENSE · RETROSPECTIVO",
              color=_BLUE, size=10, bold_all=True)
    band = doc.add_table(rows=1, cols=1)
    cell = band.rows[0].cells[0]
    _shade(cell, _NAVY_HEX)
    _add_runs(cell.paragraphs[0], meta["nombre"], color=_WHITE, size=22, bold_all=True)
    _add_runs(doc.add_paragraph(),
              "Anatomía de una quiebra · reconstrucción del deterioro sobre dato mensual real",
              color=_BLUE, size=12)

    # ── Veredicto (pull-quote) ──
    lead = bt.get("lead_months")
    verdict = (f"Deterioro detectable desde {bt.get('onset_cluster')} — {lead} meses antes del "
               f"colapso." if bt.get("onset_cluster") and lead is not None
               else "Los ratios reportados nunca formaron un cluster de alerta antes de la salida.")
    vq = doc.add_paragraph()
    _left_accent(vq, _SIGNAL)
    _add_runs(vq, verdict, color=_NAVY, size=13)

    # ── Tabla-resumen (4 cifras) ──
    mora_max = (f"{ctx['morosidad_maxima_pct']:.1f}%"
                if ctx.get("morosidad_maxima_pct") is not None else "—")
    stat_head = ["Inicio del deterioro", "Anticipación", "Morosidad máx.", "Meses en alerta"]
    stat_vals = [bt.get("onset_cluster") or "—",
                 f"{lead} meses" if lead is not None else "—",
                 mora_max,
                 f"{bt.get('n_high_months', 0)} de {meta['n_periodos']}"]
    t = doc.add_table(rows=0, cols=4)
    t.style = "Light Grid Accent 1"
    for ri, row in enumerate((stat_head, stat_vals)):
        cells = t.add_row().cells
        for ci, val in enumerate(row):
            _add_runs(cells[ci].paragraphs[0], str(val),
                      color=(_WHITE if ri == 0 else None), bold_all=(ri == 0))
            if ri == 0:
                _shade(cells[ci], _NAVY_HEX)

    # ── Gráficos del dato real (reusa los del PDF) + narrativa + fuentes ──
    tmp = tempfile.mkdtemp(prefix="forensic_docx_")
    try:
        c1, c2 = os.path.join(tmp, "credito.png"), os.path.join(tmp, "dep.png")
        _chart_credito(series, c1)
        _chart_deposito(series, c2)
        _add_runs(doc.add_paragraph(), "Riesgo de crédito y colchón de provisiones",
                  color=_NAVY, size=14, bold_all=True)
        doc.add_picture(c1, width=Inches(6.2))
        _add_runs(doc.add_paragraph(), "Fuga de depósitos (variación intermensual)",
                  color=_NAVY, size=14, bold_all=True)
        doc.add_picture(c2, width=Inches(6.2))

        _add_runs(doc.add_paragraph(), "Lectura forense", color=_NAVY, size=15, bold_all=True)
        if narrative_md and not degraded:
            _md_body(doc, narrative_md)
        else:
            _add_runs(doc.add_paragraph(),
                      "La lectura narrativa no está disponible en este momento; los datos y el "
                      "backtest de arriba son completos.")

        _add_runs(doc.add_paragraph(), "Metodología y fuentes", color=_NAVY, size=15, bold_all=True)
        _add_runs(doc.add_paragraph(),
                  "Todas las cifras salen del estado de situación y de resultados mensual por "
                  "entidad publicado por la Superintendencia de Bancos (Cronología SB). El inicio "
                  "del deterioro es el primer mes con un cluster de ≥2 alertas altas simultáneas.")
        _add_runs(doc.add_paragraph(),
                  "Límite: el capital regulatorio Basilea no existe en el balance contable "
                  "pre-2004 — el apalancamiento patrimonio/activos es un proxy etiquetado. Informe "
                  "retrospectivo/forense, no una calificación emitida en su momento.",
                  color=_GRAY, size=8)

        _add_runs(doc.add_paragraph(), "Disclaimer", color=_BLUE, size=12, bold_all=True)
        _add_runs(doc.add_paragraph(), DISCLAIMER_ES, color=_GRAY, size=8)

        buf = BytesIO()
        doc.save(buf)
        return buf.getvalue()
    finally:
        for f in (os.path.join(tmp, "credito.png"), os.path.join(tmp, "dep.png")):
            if os.path.exists(f):
                os.remove(f)
        os.rmdir(tmp)
