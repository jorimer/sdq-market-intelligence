"""The Excel template handed to the research provider.

Deliberately a *long* (tidy) layout: one row per measurement, rather than a grid of
metrics as columns. A grid would need a new column — and a schema change — for every
indicator a client adds. The long shape absorbs any tracker without touching the model,
which is what lets a second client onboard by filling a spreadsheet.

Five sheets:
  Encargo         — the mandate's identity.
  Olas            — one row per wave, with fieldwork window and nominal base.
  Marcas          — the competitive set, and which brands count toward the denominator.
  Observaciones   — the data. One row per wave x brand x metric x segment.
  Diccionario     — the metric vocabulary, so whoever fills it in has the codes at hand.

``base_n`` is a first-class column, not an afterthought: it is what makes every confidence
band computable. A row without it is loaded and displayed but can never sustain a verdict.
"""
from __future__ import annotations

import io
from typing import Optional

from openpyxl import Workbook
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter

from modules.brand_intel.engines.metrics import METRICS

_NAVY = "0B1F3A"
_HEADER_FONT = Font(bold=True, color="FFFFFF", size=10)
_HEADER_FILL = PatternFill("solid", fgColor=_NAVY)
_NOTE_FONT = Font(italic=True, size=9, color="6B7A8F")


def _write_header(ws, headers, widths) -> None:
    for i, (h, w) in enumerate(zip(headers, widths), start=1):
        cell = ws.cell(row=1, column=i, value=h)
        cell.font = _HEADER_FONT
        cell.fill = _HEADER_FILL
        cell.alignment = Alignment(horizontal="left", vertical="center")
        ws.column_dimensions[get_column_letter(i)].width = w
    ws.freeze_panes = "A2"


def build_template(
    engagement_slug: str = "",
    focal_brand: str = "",
    client_name: str = "",
    provider: str = "",
) -> bytes:
    """Return the .xlsx template as bytes, optionally pre-filled with the mandate."""
    wb = Workbook()

    # ── Encargo ────────────────────────────────────────────────────
    ws = wb.active
    ws.title = "Encargo"
    _write_header(ws, ["campo", "valor", "nota"], [26, 40, 62])
    rows = [
        ("slug", engagement_slug, "Identificador estable del encargo. Ej: mcdonalds-rd"),
        ("cliente", client_name, "Quién contrata el estudio."),
        ("marca_focal", focal_brand, "La marca sobre la que trata el informe."),
        ("mercado", "República Dominicana", "País o mercado del estudio."),
        ("categoria", "", "Categoría competitiva. Ej: QSR, banca minorista."),
        ("proveedor", provider, "Proveedor de investigación. Ej: Ipsos Dominicana."),
    ]
    for r, (k, v, note) in enumerate(rows, start=2):
        ws.cell(row=r, column=1, value=k).font = Font(bold=True, size=10)
        ws.cell(row=r, column=2, value=v)
        ws.cell(row=r, column=3, value=note).font = _NOTE_FONT

    # ── Olas ───────────────────────────────────────────────────────
    ws = wb.create_sheet("Olas")
    _write_header(
        ws,
        ["codigo", "etiqueta", "orden", "fecha_referencia",
         "campo_inicio", "campo_fin", "base_nominal"],
        [16, 16, 8, 20, 16, 16, 14],
    )
    ws.cell(row=2, column=1, value="2025-05")
    ws.cell(row=2, column=2, value="May '25")
    ws.cell(row=2, column=3, value=1)
    ws.cell(row=2, column=7, value=300)
    ws.cell(row=3, column=1, value="(una fila por ola, en orden cronológico)").font = _NOTE_FONT

    # ── Marcas ─────────────────────────────────────────────────────
    ws = wb.create_sheet("Marcas")
    _write_header(ws, ["slug", "nombre", "es_focal", "en_set_categoria", "orden"],
                  [22, 28, 12, 20, 8])
    ws.cell(row=2, column=1, value="mcdonalds")
    ws.cell(row=2, column=2, value="McDonald's")
    ws.cell(row=2, column=3, value="SI")
    ws.cell(row=2, column=4, value="SI")
    ws.cell(row=2, column=5, value=1)
    ws.cell(row=3, column=1, value="(en_set_categoria = NO para marcas medidas "
                                   "pero fuera de la categoría)").font = _NOTE_FONT

    # ── Observaciones ──────────────────────────────────────────────
    ws = wb.create_sheet("Observaciones")
    _write_header(
        ws,
        ["entrega", "ola", "marca", "metrica", "segmento", "atributo", "valor",
         "base_n", "unidad", "fuente"],
        [22, 14, 20, 26, 20, 28, 12, 10, 10, 34],
    )
    ws.cell(row=2, column=1, value="Ola 4 · mar\'26")
    ws.cell(row=2, column=2, value="2025-05")
    ws.cell(row=2, column=3, value="mcdonalds")
    ws.cell(row=2, column=4, value="reach_7d")
    ws.cell(row=2, column=5, value="total")
    ws.cell(row=2, column=6, value="")          # atributo: vacío salvo métrica por atributo
    ws.cell(row=2, column=7, value=26)
    ws.cell(row=2, column=8, value=300)
    ws.cell(row=2, column=9, value="pct")
    ws.cell(row=2, column=10, value="Hot Tracker · lámina 18")
    ws.cell(row=3, column=1,
            value="entrega = de qué informe salió la cifra. Un tracker reexpone sus olas "
                  "anteriores en cada entrega y a veces las corrige: sin esta columna, "
                  "cargar dos informes en un mismo libro funde lo que dijo cada uno y la "
                  "cifra vigente pasa a depender del orden de las filas. "
                  "Vacío = todo el libro es una sola entrega.").font = _NOTE_FONT
    ws.cell(row=4, column=1,
            value="marca vacía = métrica de categoría · base_n vacío = el dato se muestra "
                  "pero no puede sostener un veredicto").font = _NOTE_FONT

    # ── Diccionario ────────────────────────────────────────────────
    ws = wb.create_sheet("Diccionario")
    _write_header(ws, ["metrica", "etiqueta", "tipo", "admite_banda", "nota"],
                  [26, 34, 14, 15, 60])
    for r, m in enumerate(METRICS, start=2):
        ws.cell(row=r, column=1, value=m.code)
        ws.cell(row=r, column=2, value=m.label)
        ws.cell(row=r, column=3, value=m.kind)
        ws.cell(row=r, column=4, value="SI" if m.supports_bands else "NO")
        ws.cell(row=r, column=5, value=m.description).font = _NOTE_FONT

    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def template_filename(engagement_slug: Optional[str] = None) -> str:
    base = engagement_slug or "encargo"
    return f"SDQ-MIP_plantilla_tracker_{base}.xlsx"
