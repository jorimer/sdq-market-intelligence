"""Claude-as-interpreter — the fallback when the heuristic isn't confident.

For the layouts the heuristic can't resolve, we hand Claude a small preview of the
sheet (first ~30 rows × ~12 cols) and have it emit an :class:`ExtractionSpec`
directly, via a forced tool call so the output is always valid JSON. The spec is
then cached by the workbook's ``structure_hash`` (see :mod:`engine`), so a given
layout costs one cheap call once and re-infers only when the structure changes —
a self-repairing pipeline rather than 700 hand-written parsers.

The model client is injected (``client`` arg) so this is unit-testable offline;
in production it resolves the shared Anthropic client from settings.
"""
from __future__ import annotations

import json
import logging
from typing import Any, Dict, List, Optional

from .spec import ExtractionSpec
from .workbook import Grid, Workbook
from shared.observability.llm_ledger import (  # noqa: E402
    PURPOSE_EXTRACTION, account,
)

logger = logging.getLogger("sdq.data.bcrd_excel.interpreter")

PREVIEW_ROWS = 30
PREVIEW_COLS = 12

_SPEC_TOOL = {
    "name": "emit_extraction_spec",
    "description": (
        "Emit the recipe to extract every historical time series from this BCRD "
        "Excel sheet. Periods normalize to 'YYYY-MM' (monthly), 'YYYY-Qn' "
        "(quarterly) or 'YYYY' (annual). Pick the orientation:\n"
        "- 'period_rows': each data row is one period (month in month_col, or annual "
        "when there is no month — set month_col null and year_col to the year column).\n"
        "- 'cross_tab': years across a header row AND months down a column.\n"
        "- 'matrix': periods run across a header row (years in period_header_row, an "
        "optional quarter/month row in subperiod_header_row) and each data ROW is a "
        "series whose name is in label_col (e.g. national accounts, balance of "
        "payments).\nAll row/column indices are 0-based into the previewed grid."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "orientation": {"type": "string", "enum": ["period_rows", "cross_tab", "matrix"]},
            "sheet": {"type": "string"},
            "frequency": {"type": ["string", "null"], "enum": ["monthly", "quarterly", "annual", None]},
            "data_row_start": {"type": "integer"},
            "data_row_end": {"type": ["integer", "null"]},
            "month_col": {"type": ["integer", "null"],
                          "description": "period_rows: month column; null for annual"},
            "year_col": {"type": ["integer", "null"],
                         "description": "period_rows: year column, forward-filled"},
            "subtotal_year_regex": {"type": ["string", "null"],
                                    "description": "period_rows: regex with one group "
                                    "capturing the year in trailing subtotal rows"},
            "series": {
                "type": "array",
                "description": "period_rows only: one entry per value column",
                "items": {
                    "type": "object",
                    "properties": {
                        "code": {"type": "string", "description": "short slug, e.g. 'indice'"},
                        "name": {"type": "string"},
                        "unit": {"type": ["string", "null"]},
                        "value_col": {"type": "integer"},
                    },
                    "required": ["code", "name", "value_col"],
                },
            },
            "year_header_row": {"type": ["integer", "null"], "description": "cross_tab/matrix: row of years"},
            "metric_header_row": {"type": ["integer", "null"], "description": "cross_tab"},
            "super_header_row": {"type": ["integer", "null"], "description": "cross_tab: optional super-header"},
            "period_header_row": {"type": ["integer", "null"], "description": "matrix: row of years across cols"},
            "subperiod_header_row": {"type": ["integer", "null"], "description": "matrix: row of quarters/months"},
            "label_col": {"type": ["integer", "null"], "description": "matrix: column with each row's series name"},
            "value_col_start": {"type": ["integer", "null"], "description": "cross_tab/matrix"},
            "value_col_end": {"type": ["integer", "null"], "description": "cross_tab/matrix"},
            "unit": {"type": ["string", "null"], "description": "cross_tab/matrix default unit"},
            "notes": {"type": "string"},
        },
        "required": ["orientation", "sheet", "data_row_start"],
    },
}


def render_preview(grid: Grid, rows: int = PREVIEW_ROWS, cols: int = PREVIEW_COLS) -> str:
    """Render the header region as a compact, indexed TSV for the prompt."""
    out: List[str] = [f"sheet={grid.name!r} dims={grid.nrows}x{grid.ncols}",
                      "col idx:\t" + "\t".join(f"[{c}]" for c in range(min(cols, grid.ncols)))]
    for r in range(min(rows, grid.nrows)):
        cells = []
        for c in range(min(cols, grid.ncols)):
            v = grid.cell(r, c)
            if v is None:
                cells.append("")
            elif isinstance(v, float):
                cells.append(f"{v:.4g}")
            else:
                cells.append(str(v)[:22])
        out.append(f"r{r}:\t" + "\t".join(cells))
    return "\n".join(out)


def _resolve_client(client: Any) -> Any:
    if client is not None:
        return client
    from shared.config.settings import settings
    if not settings.ANTHROPIC_API_KEY:
        raise RuntimeError(
            "Intérprete Claude no disponible: falta ANTHROPIC_API_KEY (configure la "
            "clave o use solo la heurística)."
        )
    import anthropic
    return anthropic.Anthropic(api_key=settings.ANTHROPIC_API_KEY)


def interpret_spec(
    wb: Workbook, file: str, sheet: Optional[str] = None,
    client: Any = None, model: Optional[str] = None,
) -> ExtractionSpec:
    """Ask Claude for an :class:`ExtractionSpec`; raises if no client/key."""
    grid = wb.grid(sheet)
    client = _resolve_client(client)
    if model is None:
        from shared.config.settings import settings
        model = settings.ANTHROPIC_MODEL

    preview = render_preview(grid)
    prompt = (
        "Eres un experto en extraer series de tiempo de planillas Excel del Banco "
        "Central de la República Dominicana (BCRD). Cada archivo tiene un layout a "
        "medida (cabeceras multifila, año en columna o fila dispersa, meses en "
        "español, subtotales 'Promedio YYYY', tablas cruzadas). Analiza la vista "
        "previa y emite el spec de extracción con la herramienta. Reglas: ignora "
        "filas de título/subtítulo y notas al pie; incluye SOLO columnas de valores "
        "numéricos reales; los índices son 0-based sobre la grilla mostrada.\n\n"
        f"{preview}"
    )
    response = client.messages.create(
        model=model, max_tokens=1500,
        tools=[_SPEC_TOOL], tool_choice={"type": "tool", "name": "emit_extraction_spec"},
        messages=[{"role": "user", "content": prompt}],
    )
    account(response, model=model, purpose=PURPOSE_EXTRACTION, module="macro", template="bcrd_excel")
    block = next((b for b in response.content if getattr(b, "type", None) == "tool_use"), None)
    if block is None:
        raise RuntimeError("El intérprete Claude no devolvió un spec.")
    data = dict(block.input if isinstance(block.input, dict) else json.loads(block.input))
    data.setdefault("file", file)
    data.setdefault("sheet", grid.name)
    data["structure_hash"] = wb.structure_hash()
    data["method"] = "claude"
    data["confidence"] = 0.8
    logger.info("[bcrd_excel] spec interpretado por Claude para %s", file)
    return ExtractionSpec.from_dict(data)


# ─── Nombrado semántico de series ambiguas ────────────────────────────

_NAME_TOOL = {
    "name": "emit_series_names",
    "description": (
        "Devuelve un nombre jerárquico y legible para cada fila ambigua de la planilla."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "names": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "row": {"type": "integer", "description": "índice 0-based de la fila"},
                        "name": {
                            "type": "string",
                            "description": (
                                "nombre jerárquico separado por ' > ', del grupo más "
                                "externo a la hoja. Ej: 'Activos > Inversión de cartera > "
                                "Títulos de deuda > Bancos'"
                            ),
                        },
                    },
                    "required": ["row", "name"],
                },
            }
        },
        "required": ["names"],
    },
}


def name_ambiguous_rows(
    grid: Grid, rows: List[int], *, client: Any = None, model: Optional[str] = None,
    context_rows: int = 400,
) -> Dict[int, str]:
    """Nombre jerárquico para filas cuya etiqueta se repite en la planilla.

    Es la misma lectura que hace un analista y que la plataforma ya hace en pensiones y
    seguros: mirar la fila en su contexto —bajo qué grupo cuelga— y nombrarla por su
    posición en la jerarquía, no por su número de fila.

    Existe porque la heurística de sangría no alcanza cuando el BCRD pone el grupo y sus
    hijos en la MISMA columna y el grupo trae su propio total: ahí ni la indentación ni la
    ausencia de cifras distinguen al padre. Un lector humano lo resuelve al instante
    porque entiende QUÉ significan los rótulos; esto le pide eso mismo al modelo.

    Devuelve ``{fila: nombre}``; las filas que el modelo no resuelva quedan afuera y el
    llamador conserva su nombre anterior — nunca se inventa un rótulo.
    """
    if not rows:
        return {}
    client = _resolve_client(client)
    if model is None:
        from shared.config.settings import settings
        model = settings.ANTHROPIC_MODEL

    # Contexto GENEROSO: el rótulo que distingue dos filas puede estar decenas de filas
    # arriba (el encabezado de su bloque). Con una ventana corta el modelo devolvía el
    # MISMO nombre para filas distintas —no por incapacidad, sino porque no veía al padre.
    lo = max(0, min(rows) - context_rows)
    hi = min(grid.nrows, max(rows) + 5)
    lines = []
    for r in range(lo, hi):
        cells = []
        for c in range(0, min(grid.ncols, 8)):
            v = grid.cell(r, c)
            if v not in (None, ""):
                cells.append(f"c{c}={str(v)[:40]}")
        if cells:
            mark = "  <<< NOMBRAR" if r in rows else ""
            lines.append(f"fila {r}: " + " | ".join(cells) + mark)

    prompt = (
        "Eres analista de estadísticas macroeconómicas del Banco Central de la República "
        "Dominicana. En esta planilla varias filas comparten la misma etiqueta (p.ej. "
        "'Bancos' u 'Otros Sectores' aparecen bajo distintos grupos), y necesito "
        "distinguirlas por su POSICIÓN EN LA JERARQUÍA.\n\n"
        "La columna del rótulo (c0, c2, c4…) indica la sangría, pero OJO: a veces el "
        "grupo y sus hijos comparten columna, y el grupo puede traer su propio total. "
        "Usá el significado económico de los rótulos para decidir qué cuelga de qué.\n\n"
        "REGLA DURA: los nombres deben ser DISTINTOS ENTRE SÍ. Si dos filas marcadas "
        "reciben el mismo nombre, no se pueden distinguir y el trabajo no sirve — buscá "
        "hacia arriba el encabezado de bloque, la sección o el agregado que las separa y "
        "metelo en la ruta. Si de verdad dos filas miden lo mismo, agregá al final lo que "
        "las diferencie según la planilla (el período del bloque, la columna de origen).\n\n"
        "Para cada fila marcada '<<< NOMBRAR', devolvé su nombre jerárquico completo "
        "separado por ' > ', del grupo más externo a la hoja. No inventes conceptos que "
        "no estén en la planilla.\n\n" + "\n".join(lines)
    )
    response = client.messages.create(
        model=model, max_tokens=2000,
        tools=[_NAME_TOOL], tool_choice={"type": "tool", "name": "emit_series_names"},
        messages=[{"role": "user", "content": prompt}],
    )
    account(response, model=model, purpose=PURPOSE_EXTRACTION, module="macro", template="bcrd_excel")
    block = next((b for b in response.content if getattr(b, "type", None) == "tool_use"), None)
    if block is None:
        return {}
    data = block.input if isinstance(block.input, dict) else json.loads(block.input)
    out: Dict[int, str] = {}
    wanted = set(rows)
    seen: Dict[str, int] = {}
    for item in data.get("names", []):
        try:
            r = int(item["row"])
        except (KeyError, TypeError, ValueError):
            continue
        name = str(item.get("name", "")).strip()
        if r not in wanted or not name:
            continue
        # Un nombre repetido NO se acepta: fusionaría dos series distintas. Se descarta y
        # esa fila conserva su desempate por número de fila, que es feo pero honesto.
        key = name.lower()
        if key in seen:
            logger.warning(
                "[bcrd_excel] nombre repetido '%s' para las filas %d y %d: se descarta "
                "el segundo (fusionar series distintas sería peor que un nombre feo)",
                name, seen[key], r)
            continue
        seen[key] = r
        out[r] = name
    logger.info("[bcrd_excel] Claude nombró %d de %d filas ambiguas", len(out), len(rows))
    return out
