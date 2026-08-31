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

#: La única afirmación sobre el método que el documento publica, y va UNA vez por documento.
#:
#: El informe dejó de inventariar lo que le falta (decisión del dueño, 2026-08-31): un lector
#: de un documento de calificación no lee un inventario de faltantes como rigor, lo lee como
#: producto incompleto. Lo que sí suma es la afirmación de MÉTODO — que es sobre cómo se
#: construye el índice, no sobre qué nos falta— y por eso sobrevive, consolidada.
#:
#: Vive acá y no duplicada: `_LIMITATIONS_TEXT` la COMPONE, y la ruta de calificación la
#: emite al pie. Dos textos que dicen «lo mismo» es exactamente como uno se queda atrás.
NOTA_DE_METODO_DEL_INDICE = (
    "Todo indicador del índice se sostiene en dato medido en la fuente: cuando un insumo no "
    "está disponible en el período, el indicador se excluye del promedio de su dimensión y "
    "los pesos se renormalizan sobre lo efectivamente medido, de modo que la calificación no "
    "acredita ni penaliza un dato ausente."
)

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
    "revision_anual": "Revisión Anual",
    # El año leído POR DENTRO, del producto trimestral. Sin esta entrada el informe salía
    # rotulado «Revisión Anual» —el nombre del OTRO producto— en la portada y en el
    # encabezado de cada página: la confusión exacta que la separación vino a cerrar,
    # reintroducida por el rótulo.
    "anio_por_trimestres": "Año por Trimestres",
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
    "mapa_sectorial": "Mapa Sectorial del Crédito",
    "mapa_sectorial_sistema": "El Crédito del Sistema por Sector",
    "soporte_soberano": "Soporte y Techo Soberano",
    "early_warning": "Alerta Temprana",
    "recommendation": "Recomendación",
    "trend_analysis": "Análisis de Tendencias",
    "sector_outlook": "Perspectiva Sectorial",
    "anuario": "Anuario",
    "revision_anual": "Revisión Anual",
    # Sin esta línea el fallback `clave.replace("_", " ").title()` imprimía «Anio Por
    # Trimestres»: sin eñe, porque la CLAVE no la lleva, y con la capitalización de un
    # identificador. Un título de sección de un documento que se vende no se deriva de un
    # nombre de variable.
    "anio_por_trimestres": "El Año por Trimestres",
    "contexto_de_mercado": "Contexto de Mercado",
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
        # UN INDICADOR NO DISPONIBLE NO SE PUBLICA. Ni con su valor ni marcado.
        #
        # Cuando falta un insumo, el motor lo marca `available=False`, lo excluye del
        # promedio de su dimensión y renormaliza los pesos. Esta tabla llegó a leer igual su
        # `raw` —el 0.0 por defecto de la estructura— y su score: en los indicadores
        # INVERSOS ese cero puntúa 100, así que un dato ausente salía como desempeño
        # perfecto. Eso no puede volver, y el test lo vigila.
        #
        # La primera cura fue publicar la fila marcada «s/d». Correcta hacia adentro y
        # dañina hacia afuera: el lector de un informe de calificación no lee rigor en un
        # inventario de faltantes, lee un producto incompleto. Decisión del dueño
        # (2026-08-31): lo que no se puede afirmar no se menciona. La fila se omite y la
        # afirmación de MÉTODO —que el índice se sostiene solo en dato real y que un
        # indicador sin insumo se excluye renormalizando— vive una sola vez, en
        # Limitaciones, que es donde ese lector la busca.
        #
        # Lo que NO cambia es hacia adentro: nunca se fabrica, nunca se acredita el hueco.
        if data.get("available") is False:
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

        # Tres de los cinco indicadores de Solidez —solvencia, solvencia de capital primario
        # y capital primario/activos ponderados— miden capital sobre activos ponderados por
        # riesgo. Cuando la entidad no tiene capital secundario, dos de ellos COINCIDEN
        # exactamente, y un lector razonable los leería como tres evidencias independientes.
        # Se declara en vez de esconderse: la alternativa —recomponer la dimensión— mueve el
        # score de todas las entidades y es una decisión de metodología, no una nota al pie.
        nota = _nota_de_capital_redundante(indicators)
        if nota:
            elements.append(Spacer(1, 0.06 * inch))
            elements.append(Paragraph(nota, styles["SDQSmall"]))

    return elements


def _nota_de_capital_redundante(indicators: Dict) -> Optional[str]:
    """La advertencia cuando dos ratios de capital dan el MISMO número, o ninguna."""
    def _raw(clave):
        blob = (indicators or {}).get(clave)
        return blob.get("raw") if isinstance(blob, dict) else None

    sol, lev = _raw("solvencia"), _raw("leverage")
    if sol is None or lev is None or abs(float(sol) - float(lev)) > 0.005:
        return None
    return ("Nota: «Índice de solvencia» y «Capital primario / activos ponderados» coinciden "
            "en este período porque la entidad no registra capital secundario — comparten "
            "numerador y denominador. Son el mismo hecho medido dos veces, no dos evidencias "
            "independientes de solidez.")


#: Rótulos de las cinco dimensiones. Se declaran acá y no se derivan de la clave: `aap` ya
#: nos enseñó que una clave cruda impresa es material de mercado con jerga interna.
_DIMENSION_LABEL = {
    "solidez": "Solidez Financiera", "calidad": "Calidad de Activos",
    "eficiencia": "Eficiencia y Rentabilidad", "liquidez": "Liquidez",
    "diversificacion": "Diversificación",
}


def _nota_de_capital_del_balance(balance: List[Dict]) -> Optional[str]:
    """La misma advertencia del Deep Dive trimestral, leída desde las filas del balance.

    No se reusa `_nota_de_capital_redundante` porque las dos superficies traen formas
    distintas —allá un dict `{clave: {raw}}`, acá una lista de filas— y adaptar una a la otra
    escondería la diferencia. Lo que NO se duplica es el TEXTO: es el mismo, y se toma de
    aquella función para que no puedan divergir.
    """
    por_clave = {str(f.get("indicador")): f for f in (balance or [])}
    sol, lev = por_clave.get("solvencia"), por_clave.get("leverage")
    if not sol or not lev:
        return None
    a, b = sol.get("cierre"), lev.get("cierre")
    if a is None or b is None or abs(float(a) - float(b)) > 0.005:
        return None
    return _nota_de_capital_redundante(
        {"solvencia": {"raw": a}, "leverage": {"raw": b}})


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


def _build_anio_por_trimestres_tables(dentro: Dict, styles) -> List:
    """Las tablas del año POR DENTRO: la serie de los trimestres y el movimiento de cada tramo.

    Responden CUÁNDO, que es la pregunta de este producto. La serie sola da el nivel de cada
    corte; la columna de cambio da el tramo, y es lo que distingue «cayó todo el año» de «cayó
    en el cuarto trimestre» — dos años distintos con el mismo cierre.
    """
    if not dentro:
        return []
    elementos: List = []

    serie = dentro.get("serie") or []
    if serie:
        elementos.append(Paragraph(f"El año {dentro.get('anio', '')} trimestre a trimestre",
                                   styles["SDQHeading"]))
        filas = [["Corte", "Score", "Resiliencia", "Banda", ""]]
        for p in serie:
            filas.append([
                str(p.get("corte", ""))[:7],
                f"{p['score']:.2f}" if isinstance(p.get("score"), (int, float)) else "—",
                f"{p['resiliencia']:.2f}" if isinstance(p.get("resiliencia"), (int, float)) else "—",
                str(p.get("banda") or "—"),
                # La línea base se MARCA: sin eso el año parecería tener cinco trimestres.
                "línea base" if p.get("es_linea_base") else ""])
        elementos.append(_branded_table(
            filas, [0.95 * inch, 0.9 * inch, 1.05 * inch, 1.45 * inch, 0.95 * inch],
            styles, font_size=9.5, padding=5))
        elementos.append(Paragraph(
        "La banda corresponde al eje de RESILIENCIA, no al score global: Resiliencia "
        "reagrega solidez, calidad, liquidez y diversificación, y excluye eficiencia. "
        "Por eso un score global mayor puede convivir con una banda menor.",
        styles["SDQSmall"]))

        elementos.append(Spacer(1, 0.2 * inch))

    tramos = dentro.get("tramos") or []
    if tramos:
        elementos.append(Paragraph("Movimiento de cada trimestre", styles["SDQHeading"]))
        filas = [["Trimestre", "Desde", "Hasta", "Cambio", "Dirección"]]
        for t in tramos:
            filas.append([
                str(t.get("tramo", "")),
                f"{t['score_desde']:.2f}" if isinstance(t.get("score_desde"), (int, float)) else "—",
                f"{t['score_hasta']:.2f}" if isinstance(t.get("score_hasta"), (int, float)) else "—",
                f"{t['cambio']:+.2f}" if isinstance(t.get("cambio"), (int, float)) else "—",
                str(t.get("direccion") or "—")])
        elementos.append(_branded_table(
            filas, [1.7 * inch, 0.9 * inch, 0.9 * inch, 0.9 * inch, 1.2 * inch],
            styles, font_size=9.5, padding=5))
        mayor = dentro.get("tramo_que_mas_movio") or {}
        if mayor.get("cuota_del_movimiento_pct") is not None:
            elementos.append(Spacer(1, 0.08 * inch))
            elementos.append(Paragraph(
                f"El {mayor['tramo']} concentró el {mayor['cuota_del_movimiento_pct']:.1f} % "
                "del movimiento del año. La cuota se mide sobre la suma de los movimientos en "
                "valor absoluto: sobre el neto, un año que baja y sube daría cuotas por encima "
                "del 100 % sin que nada esté mal.", styles["SDQSmall"]))
        elementos.append(Spacer(1, 0.25 * inch))

    faltantes = dentro.get("cortes_faltantes") or []
    if faltantes:
        elementos.append(Paragraph(
            "Cortes ausentes en el año: " + ", ".join(str(c) for c in faltantes)
            + ". Un tramo sin su corte no se puede medir; callarlo haría pasar tres trimestres "
            "por cuatro.", styles["SDQSmall"]))
        elementos.append(Spacer(1, 0.2 * inch))
    return elementos


def _build_anio_contra_anios_tables(rev: Dict, styles) -> List:
    """Las tablas del año CONTRA los años: la serie de cierres y la tendencia.

    «Cerró en 58,71» no dice si es un mal año o el cuarto consecutivo bajando, y son
    decisiones de exposición distintas. La serie de cierres es lo único que lo separa.
    """
    if not rev:
        return []
    elementos: List = []

    serie = rev.get("serie_de_cierres") or []
    if serie:
        elementos.append(Paragraph("Cierres anuales", styles["SDQHeading"]))
        # La banda NO sale de la columna «Score»: sale del eje de Resiliencia, que es otro
        # número. Publicarlas pegadas sin decirlo hizo que un analista externo leyera los
        # umbrales como arbitrarios —vio 60,06 «En vigilancia» y 59,73 «Adecuada»— cuando lo
        # que variaba era la cifra que no estábamos mostrando.
        filas = [["Año", "Score", "Resiliencia", "Banda", "vs. año anterior"]]
        cambios = {v["anio"]: v for v in (rev.get("variaciones") or [])}
        for p in serie:
            v = cambios.get(p.get("anio"))
            filas.append([
                str(p.get("anio", "")),
                f"{p['score']:.2f}" if isinstance(p.get("score"), (int, float)) else "—",
                f"{p['resiliencia']:.2f}" if isinstance(p.get("resiliencia"), (int, float)) else "—",
                str(p.get("banda") or "—"),
                f"{v['cambio']:+.2f}" if v and isinstance(v.get("cambio"), (int, float)) else "—"])
        elementos.append(_branded_table(
            filas, [0.75 * inch, 0.95 * inch, 1.05 * inch, 1.5 * inch, 1.15 * inch],
            styles, font_size=9.5, padding=5))
        elementos.append(Paragraph(
        "La banda corresponde al eje de RESILIENCIA, no al score global: Resiliencia "
        "reagrega solidez, calidad, liquidez y diversificación, y excluye eficiencia. "
        "Por eso un score global mayor puede convivir con una banda menor.",
        styles["SDQSmall"]))

        t = rev.get("tendencia") or {}
        if t.get("lectura"):
            elementos.append(Spacer(1, 0.08 * inch))
            nota = str(t["lectura"]) + "."
            # El horizonte se DECLARA: seis cierres no son «siempre», y el límite es NUESTRO
            # backfill, no el de la fuente.
            if t.get("por_que_este_horizonte"):
                nota += " " + str(t["por_que_este_horizonte"])
            elementos.append(Paragraph(nota, styles["SDQSmall"]))
        elementos.append(Spacer(1, 0.25 * inch))

    cambios_banda = [v for v in (rev.get("variaciones") or []) if v.get("cambio_de_banda")]
    if cambios_banda:
        elementos.append(Paragraph("Cambios de banda entre años", styles["SDQHeading"]))
        filas = [["Año", "Desde", "Hasta"]]
        for v in cambios_banda:
            filas.append([str(v["anio"]), str(v["cambio_de_banda"]["desde"] or "—"),
                          str(v["cambio_de_banda"]["hasta"] or "—")])
        elementos.append(_branded_table(filas, [1.4 * inch, 1.9 * inch, 1.9 * inch],
                                        styles, font_size=9.5, padding=5))
        elementos.append(Spacer(1, 0.25 * inch))
    return elementos


def _build_revision_anual_tables(rev: Dict, styles) -> List:
    """Las tablas del AÑO de una entidad: el camino, las bandas y el balance apertura/cierre.

    Se imprimen porque son el hecho que la foto de diciembre NO da. Dos entidades con el mismo
    score de cierre —una estable, otra que cayó y se recuperó— tienen el mismo informe al
    corte y años distintos; la tabla del camino es lo que las separa.

    El balance lleva la APERTURA al lado del cierre a propósito: solvencia, apalancamiento y
    liquidez son STOCKS, y su valor de diciembre no dice nada del año sin el nivel del que
    partió. Es el dato que hasta ahora no existía en ningún informe.
    """
    if not rev:
        return []
    elements: List = []

    # La serie de cierres anuales y la tendencia van primero: son el sujeto del producto.
    elements.extend(_build_anio_contra_anios_tables(rev, styles))

    serie = rev.get("serie") or []
    if serie:
        elements.append(Paragraph(f"El año {rev.get('anio', '')}", styles["SDQHeading"]))
        rows = [["Corte", "Score", "Resiliencia", "Banda"]]
        rows += [[str(p.get("corte", ""))[:7],
                  f"{p['score']:.2f}" if isinstance(p.get("score"), (int, float)) else "—",
                  f"{p['resiliencia']:.2f}" if isinstance(p.get("resiliencia"), (int, float)) else "—",
                  str(p.get("banda") or "—")] for p in serie]
        elements.append(_branded_table(
            rows, [1.1 * inch, 1.0 * inch, 1.1 * inch, 1.9 * inch],
            styles, font_size=9.5, padding=5))
        elements.append(Paragraph(
        "La banda corresponde al eje de RESILIENCIA, no al score global: Resiliencia "
        "reagrega solidez, calidad, liquidez y diversificación, y excluye eficiencia. "
        "Por eso un score global mayor puede convivir con una banda menor.",
        styles["SDQSmall"]))

        ap, ci = rev.get("apertura") or {}, rev.get("cierre") or {}
        nota = (f"Apertura {ap.get('score', '—')} → cierre {ci.get('score', '—')} "
                f"({rev.get('cambio_score', 0):+.2f} puntos). "
                "El score del año es el DEL CIERRE: no se promedian los trimestres.")
        cam = rev.get("camino") or {}
        if cam.get("lectura"):
            nota += " " + str(cam["lectura"]) + "."
        elements.append(Spacer(1, 0.08 * inch))
        elements.append(Paragraph(nota, styles["SDQSmall"]))
        elements.append(Spacer(1, 0.25 * inch))

    cambios = rev.get("cambios_de_banda") or []
    if cambios:
        elements.append(Paragraph("Cambios de banda durante el año", styles["SDQHeading"]))
        rows = [["Corte", "Desde", "Hasta"]]
        rows += [[str(c.get("corte", ""))[:7], str(c.get("desde") or "—"),
                  str(c.get("hasta") or "—")] for c in cambios]
        elements.append(_branded_table(rows, [1.4 * inch, 1.9 * inch, 1.9 * inch],
                                       styles, font_size=9.5, padding=5))
        elements.append(Spacer(1, 0.25 * inch))

    # QUÉ DIMENSIÓN hizo el año. Va ANTES del detalle por indicador: es la respuesta, y el
    # balance de veinte indicadores es el sustento. El Deep Dive trimestral imprime los
    # sub-componentes y el anual no los tenía — el mismo hueco que el nivel de referencia.
    dims = rev.get("balance_por_dimension") or []
    if dims:
        elements.append(Paragraph("Qué dimensión movió el año", styles["SDQHeading"]))
        rows = [["Dimensión", "Peso", "Apertura", "Cierre", "Aporte al cambio"]]
        for d in dims:
            ap, ci = d.get("apertura"), d.get("cierre")
            rows.append([
                _DIMENSION_LABEL.get(str(d.get("dimension")), str(d.get("dimension"))),
                f"{float(d.get('peso') or 0) * 100:.0f}%",
                f"{ap:.2f}" if isinstance(ap, (int, float)) else "—",
                f"{ci:.2f}" if isinstance(ci, (int, float)) else "—",
                (f"{d['aporte_al_cambio']:+.2f}"
                 if isinstance(d.get("aporte_al_cambio"), (int, float)) else "—")])
        elements.append(_branded_table(
            rows, [1.9 * inch, 0.7 * inch, 1.0 * inch, 1.0 * inch, 1.3 * inch],
            styles, font_size=9.5, padding=5))
        rec = rev.get("reconciliacion_del_cambio") or {}
        if rec.get("suma_de_aportes") is not None:
            elements.append(Spacer(1, 0.08 * inch))
            elements.append(Paragraph(
                f"Aporte = variación del sub-componente × su peso. Suman "
                f"{rec['suma_de_aportes']:+.2f} puntos, el cambio del score del año. "
                "Las filas se muestran redondeadas, así que sumarlas a mano puede diferir en "
                "un centésimo.", styles["SDQSmall"]))
        elements.append(Spacer(1, 0.25 * inch))

    bal = rev.get("balance") or []
    if bal:
        elements.append(Paragraph("Balance: apertura contra cierre", styles["SDQHeading"]))
        # El SCORE al lado del valor: el trimestral lo imprime y acá faltaba, así que una
        # cobertura que baja de 147,82 % a 108,36 % no dejaba ver que su score cedió 13,72
        # puntos — que es lo que mueve la calificación.
        rows = [["Indicador", "Apertura", "Cierre", "Cambio", "Score ap.", "Score ci."]]
        for f in bal:
            rotulo, cierre_txt = _rotulo_y_valor(str(f.get("indicador", "")), f.get("cierre"))
            _, apertura_txt = _rotulo_y_valor(str(f.get("indicador", "")), f.get("apertura"))
            cambio = f.get("cambio")
            s_ap, s_ci = f.get("score_apertura"), f.get("score_cierre")
            rows.append([rotulo, apertura_txt, cierre_txt,
                         f"{cambio:+.2f}" if isinstance(cambio, (int, float)) else "—",
                         f"{s_ap:.1f}" if isinstance(s_ap, (int, float)) else "—",
                         f"{s_ci:.1f}" if isinstance(s_ci, (int, float)) else "—"])
        elements.append(_branded_table(
            rows, [2.0 * inch, 1.0 * inch, 1.0 * inch, 0.85 * inch, 0.8 * inch, 0.8 * inch],
            styles, font_size=9, padding=4))
        elements.append(Spacer(1, 0.08 * inch))
        elements.append(Paragraph(
            "Los indicadores de balance son fotos a cada corte: el nivel de diciembre no "
            "describe el año sin el nivel del que partió.", styles["SDQSmall"]))
        # La MISMA nota que el Deep Dive trimestral. Faltaba acá, y el anual publicaba dos
        # filas de capital con el número idéntico sin decir por qué — un lector razonable lo
        # lee como un error nuestro.
        nota_cap = _nota_de_capital_del_balance(bal)
        if nota_cap:
            elements.append(Spacer(1, 0.06 * inch))
            elements.append(Paragraph(nota_cap, styles["SDQSmall"]))
        elements.append(Spacer(1, 0.25 * inch))

    faltantes = rev.get("cortes_faltantes") or []
    if faltantes:
        # Se DECLARA: el pico de una serie con huecos es el pico de lo que se vio, no el del
        # año, y ocultarlo haría pasar una lectura parcial por completa.
        elements.append(Paragraph(
            "Cortes ausentes en el año: " + ", ".join(str(c) for c in faltantes)
            + ". Las anclas del camino son de los cortes disponibles, no del año completo.",
            styles["SDQSmall"]))
        elements.append(Spacer(1, 0.2 * inch))
    return elements


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


def _build_narrative_sections(narratives: Dict[str, str], styles,
                              tablas: Optional[Dict[str, List]] = None) -> List:
    """Las secciones narrativas, con su tabla DENTRO del texto cuando la hay.

    El resto de las tablas del informe vive en un bloque de datos separado de la narrativa
    por un salto de página. Eso funciona para las que encuadran el documento entero —el
    telón macro, la estructura de mercado—, pero no para una tabla que ES el argumento de
    su sección: mandarla veinte páginas atrás obliga al lector a sostener nueve columnas de
    memoria mientras lee el párrafo que las interpreta. `tablas` mapea clave de sección a
    flowables, y se emiten inmediatamente después del texto que los explica."""
    elements: List = []
    n = 0
    for section_key, text in narratives.items():
        title = NARRATIVE_SECTION_TITLES.get(
            section_key, section_key.replace("_", " ").title(),
        )
        n += 1
        elements.append(Paragraph(f"{n}. {title}", styles["SDQHeading"]))
        elements.extend(_md_to_flowables(text or "", styles))
        for el in (tablas or {}).get(section_key) or []:
            elements.append(el)
        elements.append(Spacer(1, 0.2 * inch))
    return elements


def _build_disclaimer(styles, con_nota_de_metodo: bool = False) -> List:
    """El pie del documento. `con_nota_de_metodo` lo enciende quien publicó el índice.

    Se ata a la PRESENCIA de la tabla de indicadores y no a una lista de tipos de informe:
    una lista es lo que alguien olvida actualizar al agregar un tipo, y este repo ya tiene
    el antecedente —al anuario le faltaron cuatro registros de a uno y ninguno falló—.
    """
    elements: List = []
    if con_nota_de_metodo:
        elements.append(Spacer(1, 0.35 * inch))
        elements.append(Paragraph(NOTA_DE_METODO_DEL_INDICE, styles["SDQSmall"]))
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


# Fuente única: había otra copia en `api/router_scoring.py` que no coincidía.
from modules.banking_score.etiquetas import TIPO_LABEL as _TIPO_LABEL  # noqa: E402

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


#: Cuántos sectores entran en la tabla. El corte es por EXPOSICIÓN, y lo que queda afuera se
#: DECLARA al pie: un tope silencioso se lee como «esto es todo lo que hay».
_MAX_SECTORES_EN_TABLA = 8

_ATRIBUCION_LABEL = {
    "idiosincratico_peor": "Propia",
    "idiosincratico_mejor": "Propia (mejor)",
    "compartido_con_el_sector": "Del sector",
    "exposicion_no_material": "No material",
    "sin_resto_con_que_comparar": "Único prestador",
    "sin_dato": "—",
}


def _pp(v: Optional[float]) -> str:
    """Un punto porcentual CON SU SIGNO. El signo es la relación —y la relación se computa
    acá y se imprime; no se le pide al lector que la derive de dos columnas."""
    return "—" if v is None else f"{v:+.2f}"


def _num(v: Optional[float], suf: str = "") -> str:
    return "—" if v is None else f"{v:.2f}{suf}"


def _build_sector_map_table(mapa: Dict, styles) -> List:
    """La tabla del mapa sectorial: la entidad contra el RESTO del sistema, sector a sector.

    Va DENTRO de su sección y no en el bloque de datos, porque es el argumento del párrafo
    que la precede: la brecha de mora y el spread de tasa se leen juntos o no se leen."""
    sectores = (mapa or {}).get("sectores") or []
    if not sectores:
        return []
    corte = mapa.get("corte")
    ttl = "Posición por sector frente al resto del sistema" + (f" · {corte}" if corte else "")
    elements: List = [Paragraph(ttl, styles["SDQSubHeading"])]
    # Las unidades van en el ENCABEZADO y las celdas quedan desnudas: con el «%» pegado a
    # cada cifra, «25.90%» no entraba en la columna y ReportLab lo partía dejando el signo
    # solo en el renglón siguiente. Y las dos columnas de referencia decían ambas «Resto»,
    # que en una tabla de nueve columnas no dice de qué es el resto: se nombran entera.
    rows = [["Sector", "% de su\ncartera", "Mora\nentidad %", "Mora\nresto %",
             "Brecha\npp", "Tasa\nentidad %", "Tasa\nresto %", "Spread\npp", "Origen"]]
    mostrados = sectores[:_MAX_SECTORES_EN_TABLA]
    for f in mostrados:
        rows.append([
            Paragraph(_md_inline(str(f.get("sector", ""))), styles["SDQSmall"]),
            _num(f.get("peso_en_su_cartera_pct")),
            _num(f.get("mora_pct")),
            _num(f.get("mora_del_resto_del_sector_pct")),
            _pp(f.get("brecha_de_mora_pp")),
            _num(f.get("tasa_promedio_ponderada_pct")),
            _num(f.get("tasa_del_resto_del_sector_pct")),
            _pp(f.get("spread_de_tasa_pp")),
            _ATRIBUCION_LABEL.get(str(f.get("atribucion")), "—"),
        ])
    table = _branded_table(
        rows,
        [1.30 * inch, 0.60 * inch, 0.58 * inch, 0.58 * inch, 0.56 * inch,
         0.58 * inch, 0.58 * inch, 0.56 * inch, 0.76 * inch],
        styles,
        aligns=["LEFT", "RIGHT", "RIGHT", "RIGHT", "RIGHT",
                "RIGHT", "RIGHT", "RIGHT", "CENTER"])
    elements.append(table)
    elements.append(Spacer(1, 0.08 * inch))
    pie = ("«Resto» es el resto del sistema en el MISMO sector, EXCLUIDA esta entidad: "
           "incluirla la compararía en parte contra sí misma. La brecha es su mora menos "
           "la del resto y el spread su tasa menos la del resto, ambos en puntos "
           "porcentuales. La tasa es un promedio ponderado por saldo adeudado. «Origen» "
           "atribuye el deterioro a la originación propia o al sector.")
    ocultos = len(sectores) - len(mostrados)
    if ocultos > 0:
        # Se DECLARA lo que no entró. Omitirlo en silencio haría leer la tabla como el
        # libro completo, y la cuota de los sectores citados como si sumara cien.
        resto_deuda = sum(float(x.get("deuda") or 0) for x in sectores[len(mostrados):])
        total = sum(float(x.get("deuda") or 0) for x in sectores) or 1.0
        pie += (f" Se muestran los {len(mostrados)} sectores de mayor exposición; los otros "
                f"{ocultos} suman el {100.0 * resto_deuda / total:.1f}% de la cartera "
                f"clasificada de la entidad.")
    elements.append(Paragraph(pie, styles["SDQSmall"]))
    return elements


def _build_system_sector_table(mapa: Dict, styles) -> List:
    """El libro de crédito del SISTEMA por sector. Otra tabla y no la de entidad con menos
    columnas: acá no hay contra qué comparar —el sujeto ES el agregado— así que las
    columnas son de composición (peso, garantía, moneda) y no de brecha."""
    sectores = (mapa or {}).get("sectores") or []
    if not sectores:
        return []
    corte = mapa.get("corte")
    ttl = "El crédito del sistema por sector" + (f" · {corte}" if corte else "")
    elements: List = [Paragraph(ttl, styles["SDQSubHeading"])]
    rows = [["Sector", "% del\ncrédito", "Entidades", "Mora\n%", "Mora 31-90\n%",
             "Tasa\n%", "Garantía\n%", "US$\n%"]]
    mostrados = sectores[:_MAX_SECTORES_EN_TABLA]
    for f in mostrados:
        rows.append([
            Paragraph(_md_inline(str(f.get("sector", ""))), styles["SDQSmall"]),
            _num(f.get("peso_en_el_sistema_pct")),
            str(f.get("entidades_que_prestan") or "—"),
            _num(f.get("mora_pct")),
            _num(f.get("mora_temprana_31_90_pct")),
            _num(f.get("tasa_promedio_ponderada_pct")),
            _num(f.get("garantia_sobre_deuda_pct")),
            _num(f.get("dolarizacion_de_la_deuda_pct")),
        ])
    table = _branded_table(
        rows,
        [1.55 * inch, 0.62 * inch, 0.72 * inch, 0.58 * inch, 0.78 * inch,
         0.58 * inch, 0.75 * inch, 0.62 * inch],
        styles,
        aligns=["LEFT", "RIGHT", "RIGHT", "RIGHT", "RIGHT", "RIGHT", "RIGHT", "RIGHT"])
    elements.append(table)
    elements.append(Spacer(1, 0.08 * inch))
    pie = ("Agrega TODAS las entidades supervisadas que prestan a cada sector. La mora de "
           "31 a 90 días se deteriora antes que la vencida, así que ordena por anticipación "
           "y no por daño consumado. La tasa es un promedio ponderado por saldo adeudado.")
    ocultos = len(sectores) - len(mostrados)
    if ocultos > 0:
        resto = sum(float(x.get("deuda") or 0) for x in sectores[len(mostrados):])
        total = sum(float(x.get("deuda") or 0) for x in sectores) or 1.0
        pie += (f" Se muestran los {len(mostrados)} sectores de mayor peso; los otros "
                f"{ocultos} suman el {100.0 * resto / total:.1f}% del crédito del sistema.")
    elements.append(Paragraph(pie, styles["SDQSmall"]))
    return elements


#: Provincias en la tabla geográfica. Son 33 y la cola es larga: se muestran las de mayor
#: exposición y lo que queda afuera se DECLARA, como en la sectorial.
_MAX_PROVINCIAS_EN_TABLA = 8


def _build_geografia_table(provincias: List[Dict], styles) -> List:
    """Dónde presta la entidad, contra dónde presta el país.

    El cubo es sector × provincia y la provincia se agregaba hasta desaparecer: existía en la
    base y no salía por ninguna superficie. Un banco ve su propia huella geográfica; lo que no
    puede ver es si sigue al mercado o se aparta de él, ni cómo le va en cada provincia contra
    el resto del país en esa misma provincia."""
    if not provincias:
        return []
    elements: List = [Paragraph("Dónde presta, contra dónde presta el país",
                                styles["SDQSubHeading"])]
    rows = [["Provincia", "% de su\ncartera", "% del\ncrédito\ndel país", "Sobre/sub\npp",
             "Mora\n%", "Mora del\npaís %", "Brecha\npp", "Sectores"]]
    mostradas = provincias[:_MAX_PROVINCIAS_EN_TABLA]
    for f in mostradas:
        rows.append([
            Paragraph(_md_inline(str(f.get("provincia", ""))), styles["SDQSmall"]),
            _num(f.get("peso_en_su_cartera_pct")),
            _num(f.get("peso_de_la_provincia_en_el_pais_pct")),
            _pp(f.get("sobre_representacion_pp")),
            _num(f.get("mora_pct")),
            _num(f.get("mora_del_resto_del_pais_en_la_provincia_pct")),
            _pp(f.get("brecha_de_mora_pp")),
            str(f.get("sectores_en_que_presta") or "—"),
        ])
    table = _branded_table(
        rows,
        [1.40 * inch, 0.62 * inch, 0.70 * inch, 0.66 * inch, 0.52 * inch, 0.66 * inch,
         0.60 * inch, 0.62 * inch],
        styles,
        aligns=["LEFT"] + ["RIGHT"] * 7)
    elements.append(table)
    elements.append(Spacer(1, 0.08 * inch))
    pie = ("Las dos primeras columnas tienen denominadores DISTINTOS: la primera es sobre la "
           "cartera clasificada de la entidad y la segunda sobre el crédito de todo el país. "
           "«Sobre/sub» es la diferencia entre ambas: positiva, la entidad pesa más en esa "
           "provincia que el mercado. «SIN PROVINCIA» es la porción del libro cuyo rótulo la "
           "fuente no trae y se muestra para que las cuotas sumen cien.")
    ocultas = len(provincias) - len(mostradas)
    if ocultas > 0:
        resto = sum(float(x.get("deuda") or 0) for x in provincias[len(mostradas):])
        total = sum(float(x.get("deuda") or 0) for x in provincias) or 1.0
        pie += (f" Se muestran las {len(mostradas)} de mayor exposición; las otras "
                f"{ocultas} suman el {100.0 * resto / total:.1f}% de la cartera.")
    elements.append(Paragraph(pie, styles["SDQSmall"]))
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
    revision: Optional[Dict] = None,
    anio_dentro: Optional[Dict] = None,
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
    _publico_el_indice = bool(indicators) and report_type in ("full_rating", "scorecard",
                                                             "datawatch")
    if _publico_el_indice:
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

    # 3a-quater. REVISIÓN ANUAL — el año de la ENTIDAD. Mismo criterio que el anuario: son
    # el sujeto del documento, no un anexo.
    if revision:
        body.extend(_build_revision_anual_tables(revision, styles))
    # El año POR DENTRO — otro producto, otras tablas. Va aparte de `revision` a propósito:
    # colapsarlos en un parámetro es cómo los dos productos terminaron sirviendo el mismo
    # informe en primer lugar.
    if anio_dentro:
        body.extend(_build_anio_por_trimestres_tables(anio_dentro, styles))

    # 3b. Pulse — distribución del sistema por banda (opt-in, anonimizado).
    if band_distribution:
        body.extend(_build_band_distribution_table(band_distribution, styles))
        body.append(Spacer(1, 0.3 * inch))

    # ── 3c-3f. Las tablas que PERTENECEN a una sección ──────────────────────────────
    #
    # Cada una de estas cuatro es el respaldo de un párrafo concreto, no del documento: la
    # de pares sostiene el comparativo, la macro el entorno operativo, la de soporte su
    # propia sección y la de sensibilidad la recomendación —que es donde se dice qué palanca
    # mover—. Impresas todas juntas veinte páginas antes del texto que las interpreta,
    # obligan al lector a sostener de memoria lo que debería tener al lado.
    #
    # A diferencia de las de arriba —cuadro de mando, indicadores, trayectoria—, que sí
    # encuadran el documento entero y por eso siguen abriendo.
    #
    # Si la sección dueña NO se está narrando (un `scorecard` no lleva comparativo), la
    # tabla vuelve al bloque de datos en vez de desaparecer: perder una tabla en silencio
    # por reordenar el documento sería exactamente el defecto que este cambio evita.
    tablas_en_linea: Dict[str, List] = {}
    secciones_narradas = set(narratives or {})
    if sections:
        secciones_narradas &= set(sections)

    def _colocar(seccion: str, elementos: List) -> None:
        if not elementos:
            return
        if seccion in secciones_narradas:
            tablas_en_linea[seccion] = elementos
        else:
            body.extend(elementos)
            body.append(Spacer(1, 0.3 * inch))

    if peer_block:
        _colocar("comparative", _build_peer_block(peer_block, styles))

    entorno_macro = scoring_result.get("entorno_macro")
    if entorno_macro:
        _colocar("entorno_operativo", _build_macro_table(entorno_macro, styles))

    sensibilidades = scoring_result.get("sensibilidades")
    if sensibilidades:
        _colocar("recommendation", _build_sensitivity_table(sensibilidades, styles))

    soporte = scoring_result.get("soporte_soberano")
    if soporte:
        _colocar("soporte_soberano", _build_support_table(soporte, styles))

    mapa = scoring_result.get("mapa_sectorial")
    if mapa:
        els = _build_sector_map_table(mapa, styles)
        # La geografía va DEBAJO de la sectorial, en la misma sección: son dos aperturas del
        # mismo cubo y el párrafo las interpreta juntas.
        els += _build_geografia_table(mapa.get("provincias") or [], styles)
        _colocar("mapa_sectorial", els)

    mapa_sis = scoring_result.get("mapa_sectorial_sistema")
    if mapa_sis:
        _colocar("mapa_sectorial_sistema", _build_system_sector_table(mapa_sis, styles))

    # 4. Narrative sections (filtradas/ordenadas por el manifiesto si `sections`). Un único
    # salto de página separa el bloque de datos (tablas) de la narrativa; las tablas fluyen
    # naturalmente entre sí (evita páginas en blanco cuando el detalle desborda la primera).
    if narratives:
        if body:
            body.append(PageBreak())
        body.extend(_build_narrative_sections(
            _order_narratives(narratives, sections), styles, tablas_en_linea))

    # 5. Disclaimer (texto propio de banking; el shell no lo añade).
    body.extend(_build_disclaimer(styles, con_nota_de_metodo=_publico_el_indice))

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
