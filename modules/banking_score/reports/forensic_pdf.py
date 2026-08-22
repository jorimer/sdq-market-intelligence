"""Informe forense en PDF branded (reportlab + matplotlib).

Versión PDF del documento forense ("informe completo" de la vista Histórico). Usa el shell
de marca compartido (`build_branded_pdf`: portada navy + logo Arco + chrome de página) y arma
un CUERPO propio con paridad al mockup: stat cards, gráficos con marcas de onset/colapso y
mediana de pares, timeline de la lectura del modelo, dictamen de legibilidad (ratios vs
fraude) y fuentes. La lógica de negocio (fechas, cards, timeline, legibilidad) vive en
`forensic_common` para no divergir del Word. Devuelve bytes.
"""
from __future__ import annotations

import os
import tempfile
from typing import Dict, List, Optional

import matplotlib

matplotlib.use("Agg")  # sin display (servidor)
import matplotlib.pyplot as plt  # noqa: E402
from reportlab.lib.colors import HexColor  # noqa: E402
from reportlab.lib.enums import TA_LEFT  # noqa: E402
from reportlab.lib.styles import ParagraphStyle  # noqa: E402
from reportlab.lib.units import inch  # noqa: E402
from reportlab.platypus import (  # noqa: E402
    Image as RLImage,
    Paragraph,
    Spacer,
    Table,
    TableStyle,
)

from modules.banking_score.reports.forensic_common import (  # noqa: E402
    classify_exit,
    exit_label,
    headings,
    humanize_month,
    legibility,
    marker_indices,
    model_timeline,
    stat_cards,
)
from shared import brand  # noqa: E402
from modules.banking_score.reports.pdf_generator import (  # noqa: E402
    _branded_table,
    _get_styles,
    _md_to_flowables,
)

# Paleta: se LEE de `shared.brand`. Estos valores ya eran los de «Claro & Vivo», pero
# escritos a mano: una copia correcta hoy es una copia que se desincroniza mañana.
_ALERT, _WARN, _OK, _MUTED = brand.ALERT, brand.WARN, brand.OK, brand.MUTED
_PEER, _INK, _CARD_BG, _BORDER = brand.MUTED, brand.INK, brand.SURFACE_2, brand.BORDER
_TEAL = brand.TEAL
_TONE = {"alert": _ALERT, "warn": _WARN, "ok": _OK, "ink": _INK}


def _nan(v):
    return float("nan") if v is None else v


# ── Gráficos (matplotlib) con marcas de onset/colapso y ejes humanizados ────────

def _xticks(series: List[Dict]):
    n = len(series)
    step = max(1, n // 8)
    idxs = list(range(0, n, step))
    year_only = n > 36   # spans largos → solo el año; cortos → 'mmm aaaa'
    labels = [series[i]["fecha"][:4] if year_only else humanize_month(series[i]["fecha"])
              for i in idxs]
    return idxs, labels


def _style_axis(ax, series: List[Dict]) -> None:
    idxs, labels = _xticks(series)
    ax.set_xticks(idxs)
    ax.set_xticklabels(labels, fontsize=8, color=_MUTED)
    ax.tick_params(axis="y", labelsize=8, colors=_MUTED)
    ax.grid(True, color=brand.GRID, lw=0.8)
    ax.spines[["top", "right"]].set_visible(False)


def _draw_marks(ax, series: List[Dict], marks: Dict[str, Optional[int]],
                exit_txt: str = "colapso") -> None:
    top = ax.get_ylim()[1]
    for key, color, txt, ha in (("onset", _WARN, "onset", "left"),
                                ("exit", _ALERT, exit_txt, "right")):
        i = marks.get(key)
        if i is not None:
            ax.axvline(i, color=color, lw=1.2, ls=(0, (3, 3)))
            ax.text(i, top, f" {txt} · {humanize_month(series[i]['fecha'])} ",
                    color=color, fontsize=7.5, va="top", ha=ha, fontweight="bold")


def _chart_morosidad(series: List[Dict], marks: Dict, path: str, exit_txt: str = "colapso") -> None:
    xs = list(range(len(series)))
    mora = [_nan(p.get("morosidad_pct")) for p in series]
    peer = [_nan(p.get("peer_mora_pct")) for p in series]
    fig, ax = plt.subplots(figsize=(9, 3.0))
    ax.plot(xs, mora, color=_ALERT, lw=2.2, label="Entidad")
    if any(v == v for v in peer):  # noqa: PLR0124 — algún peer no-NaN
        ax.plot(xs, peer, color=_PEER, lw=1.6, ls=(0, (4, 3)), label="Mediana de su tipo")
    ax.set_ylabel("Morosidad %", fontsize=8, color=_MUTED)
    _style_axis(ax, series)
    _draw_marks(ax, series, marks, exit_txt)
    ax.legend(fontsize=8, frameon=False, loc="upper left")
    fig.savefig(path, dpi=140, bbox_inches="tight")
    plt.close(fig)


def _chart_cobertura(series: List[Dict], marks: Dict, path: str, exit_txt: str = "colapso") -> None:
    xs = list(range(len(series)))
    cob = [_nan(p.get("cobertura_pct")) for p in series]
    fig, ax = plt.subplots(figsize=(9, 2.6))
    ax.plot(xs, cob, color=_TEAL, lw=2.2)
    ax.axhline(100, color=brand.BORDER_STRONG, lw=1, ls=(0, (2, 2)))
    ax.text(0, 100, " 100% (piso Fitch)", color=_MUTED, fontsize=7, va="bottom")
    ax.set_ylabel("Cobertura %", fontsize=8, color=_MUTED)
    _style_axis(ax, series)
    _draw_marks(ax, series, marks, exit_txt)
    fig.savefig(path, dpi=140, bbox_inches="tight")
    plt.close(fig)


def _chart_deposito(series: List[Dict], marks: Dict, path: str, exit_txt: str = "colapso") -> None:
    vals = [(i, float(p["dep_mom_pct"])) for i, p in enumerate(series)
            if p.get("dep_mom_pct") is not None]
    fig, ax = plt.subplots(figsize=(9, 2.4))
    xs = [i for i, _ in vals]
    ys = [v for _, v in vals]
    ax.bar(xs, ys, color=[_ALERT if y < 0 else _OK for y in ys], width=0.7)
    ax.axhline(0, color=brand.BORDER_STRONG, lw=1)
    ax.set_ylabel("Δ depósitos %", fontsize=8, color=_MUTED)
    _style_axis(ax, series)
    _draw_marks(ax, series, marks, exit_txt)
    fig.savefig(path, dpi=140, bbox_inches="tight")
    plt.close(fig)


# ── Flowables de marca del cuerpo ───────────────────────────────────────────────

def _card_style() -> ParagraphStyle:
    return ParagraphStyle("ForensicCard", fontName="Helvetica", fontSize=10,
                          leading=13, alignment=TA_LEFT)


def _stat_cards(cards: List[Dict], styles) -> Table:
    cs = _card_style()
    cells = [Paragraph(
        f'<font size="16" color="{_TONE.get(c["tone"], _INK)}"><b>{c["value"]}</b></font><br/>'
        f'<font size="7.5" color="{_MUTED}">{c["label"]}</font>', cs) for c in cards]
    t = Table([cells], colWidths=[1.62 * inch] * 4)
    t.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), HexColor(_CARD_BG)),
        ("BOX", (0, 0), (-1, -1), 0.5, HexColor(_BORDER)),
        ("INNERGRID", (0, 0), (-1, -1), 0.5, HexColor(_BORDER)),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("TOPPADDING", (0, 0), (-1, -1), 10), ("BOTTOMPADDING", (0, 0), (-1, -1), 10),
        ("LEFTPADDING", (0, 0), (-1, -1), 10), ("RIGHTPADDING", (0, 0), (-1, -1), 10),
    ]))
    return t


def _timeline(rows: List[Dict], styles) -> List:
    out: List = []
    for r in rows:
        col = _TONE.get(r["tone"], _WARN)
        out.append(Paragraph(
            f'<font color="{col}"><b>[{r["flag"]}]</b></font> '
            f'<font color="{_INK}"><b>{r["fecha"]}</b></font> — {r["text"]}', styles["SDQBullet"]))
        out.append(Spacer(1, 3))
    return out


def _legibility_box(leg: Dict, styles) -> Table:
    col = _OK if leg["legible"] else _WARN
    bg = brand.OK_SOFT if leg["legible"] else brand.WARN_SOFT
    inner = [Paragraph(f'<font color="{col}"><b>{leg["title"]}</b></font>', styles["SDQBodyBold"]),
             Spacer(1, 3), Paragraph(leg["text"], styles["SDQBody"])]
    t = Table([[inner]], colWidths=[6.5 * inch])
    t.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), HexColor(bg)),
        ("BOX", (0, 0), (-1, -1), 0.6, HexColor(col)),
        ("TOPPADDING", (0, 0), (-1, -1), 11), ("BOTTOMPADDING", (0, 0), (-1, -1), 11),
        ("LEFTPADDING", (0, 0), (-1, -1), 12), ("RIGHTPADDING", (0, 0), (-1, -1), 12),
    ]))
    return t


def _sources_table(meta: Dict, styles) -> Table:
    rows = [
        ["Fuente", "Serie", "Cobertura"],
        ["SB — Cronología SB", "Estado de situación mensual, por entidad",
         f"{humanize_month(meta['primer'])} → {humanize_month(meta['ultimo'])}"],
        ["SB — Cronología SB", "Estado de resultados mensual, por entidad", "ene 1996 → abr 2026"],
    ]
    return _branded_table(rows, [1.9 * inch, 3.0 * inch, 1.6 * inch], styles, font_size=8)


def _img(path: str, fig_h: float) -> RLImage:
    w = 6.5 * inch
    return RLImage(path, width=w, height=w * fig_h / 9.0)


def render_forensic_pdf(pkg: Dict, narrative_md: str, *, degraded: bool = False) -> bytes:
    """Documento forense en PDF (bytes) — portada branded + cuerpo con paridad al mockup."""
    from shared.products.render import build_branded_pdf

    from modules.banking_score.historical_service import forensic_narrative_context

    meta, btk, series = pkg["meta"], pkg["backtest"], pkg["series"]
    ctx = forensic_narrative_context(pkg)
    styles = _get_styles()
    marks = marker_indices(pkg)
    kind = classify_exit(pkg, ctx)
    head = headings(pkg, ctx, kind)
    verdict = head["verdict"]
    ex_txt = exit_label(kind)

    body: List = []
    body.append(Paragraph("Resumen ejecutivo", styles["SDQHeading"]))
    body.append(_stat_cards(stat_cards(pkg, ctx, kind), styles))
    body.append(Spacer(1, 14))

    charts = tempfile.mkdtemp(prefix="forensic_pdf_")
    pdf_dir = tempfile.mkdtemp(prefix="forensic_out_")
    try:
        cm = os.path.join(charts, "mora.png")
        cc = os.path.join(charts, "cob.png")
        cd = os.path.join(charts, "dep.png")
        _chart_morosidad(series, marks, cm, ex_txt)
        _chart_cobertura(series, marks, cc, ex_txt)
        _chart_deposito(series, marks, cd, ex_txt)
        body.append(Paragraph("Riesgo de crédito — la morosidad se despega de sus pares",
                              styles["SDQSubHeading"]))
        body.append(_img(cm, 3.0))
        body.append(Spacer(1, 8))
        body.append(Paragraph("Colchón de provisiones — la cobertura se agota",
                              styles["SDQSubHeading"]))
        body.append(_img(cc, 2.6))
        body.append(Spacer(1, 8))
        body.append(Paragraph("Fuga de depósitos (variación intermensual)", styles["SDQSubHeading"]))
        body.append(_img(cd, 2.4))
        body.append(Spacer(1, 14))

        body.append(Paragraph("Qué marcó Alerta Temprana, y cuándo", styles["SDQSubHeading"]))
        body.extend(_timeline(model_timeline(pkg, ctx, kind), styles))
        body.append(Spacer(1, 8))
        body.append(_legibility_box(legibility(pkg, ctx, kind), styles))
        body.append(Spacer(1, 14))

        body.append(Paragraph("Lectura forense", styles["SDQHeading"]))
        if narrative_md and not degraded:
            body.extend(_md_to_flowables(narrative_md, styles))
        else:
            body.append(Paragraph("La lectura narrativa no está disponible en este momento; los "
                                  "datos y el backtest de arriba son completos.", styles["SDQBody"]))
        body.append(Spacer(1, 12))

        body.append(Paragraph("Metodología y fuentes", styles["SDQHeading"]))
        body.append(Paragraph(
            "Todas las cifras salen del estado de situación y de resultados mensual por entidad "
            "publicado por la Superintendencia de Bancos (Cronología SB). El onset del deterioro "
            "es el primer mes con un cluster de ≥2 alertas altas que incluye una señal de CRÉDITO "
            "(morosidad); la mediana de pares es la morosidad mensual de las entidades del mismo "
            "tipo. La naturaleza de la salida (quiebra vs otras causas) la decide el modelo leyendo "
            "los ratios en la ventana de salida.", styles["SDQBody"]))
        body.append(Spacer(1, 6))
        body.append(_sources_table(meta, styles))
        body.append(Spacer(1, 6))
        body.append(Paragraph(
            "Límite: el capital regulatorio Basilea no existe en el balance contable pre-2004 — el "
            "apalancamiento patrimonio/activos es un proxy etiquetado. Informe retrospectivo/forense, "
            "no una calificación emitida en su momento.", styles["SDQSmall"]))

        path = os.path.join(pdf_dir, "forensic.pdf")
        build_branded_pdf(
            path=path, title="Informe Forense · Retrospectivo", display_name=meta["nombre"],
            period=f"{humanize_month(meta['primer'])} → {humanize_month(meta['ultimo'])}",
            body=body, headline=verdict, subtitle=head["subtitle"],
            add_disclaimer=True)
        with open(path, "rb") as fh:
            return fh.read()
    finally:
        for d, files in ((charts, ("mora.png", "cob.png", "dep.png")), (pdf_dir, ("forensic.pdf",))):
            for f in files:
                p = os.path.join(d, f)
                if os.path.exists(p):
                    os.remove(p)
            if os.path.exists(d):
                os.rmdir(d)
