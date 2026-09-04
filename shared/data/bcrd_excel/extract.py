"""Apply an :class:`ExtractionSpec` to a workbook → normalized ``Record``s.

This layer is purely deterministic: given a (correct) spec it always produces the
same records, so it is exhaustively unit-tested against the three calibration
files. All the heterogeneity lives upstream in the spec; here we only replay it.
"""
from __future__ import annotations

import re
from datetime import date
from pathlib import Path
from typing import Dict, List, Optional

from shared.data.base_client import Record
from shared.data.lineage import Lineage

from .periods import (
    coerce_num,
    es_trimestre_acumulado,
    format_period,
    normalize_label,
    parse_month,
    parse_quarter,
    parse_year,
)
from .spec import ExtractionSpec
from .workbook import Grid, Workbook

_LICENSE = "datos oficiales BCRD — uso público con cita"


_FOOTNOTE_RE = re.compile(r"\s*\d+\s*/")  # BCRD footnote markers: "BRUTAS 1/", "2008 3/"


# Marcadores de identidad contable que el BCRD antepone a los agregados.
_MARKER_RE = re.compile(r"^\s*\(\s*[+\-=±]\s*\)\s*")

# Numeración de esquema: "I.", "II.", "1.", "1.1.", "2.3.1". Las planillas de estadística
# la usan para anidar cuando todo va en la misma columna y no hay sangría que leer. La
# numeración ES la jerarquía: 1.1 cuelga de 1, y 1 cuelga de I.
_OUTLINE_RE = re.compile(
    r"^\s*(?P<num>(?:[IVXLC]+|\d+)(?:\.\d+)*)\s*[.)]?\s+(?=\S)")


def _outline_depth(token: str) -> int:
    """Profundidad de un token de esquema. Los romanos son el nivel más externo."""
    if re.fullmatch(r"[IVXLC]+", token):
        return 1
    return 1 + token.count(".") + 1


def _clean_label(s: str) -> str:
    """Drop footnote markers so ``"BRUTAS 1/"`` and ``"BRUTAS"`` slug the same."""
    return _FOOTNOTE_RE.sub(" ", normalize_label(s)).strip()


def _slug(s: str) -> str:
    out = []
    for ch in _clean_label(s):
        out.append(ch if ch.isalnum() else "_")
    slug = "".join(out)
    while "__" in slug:
        slug = slug.replace("__", "_")
    return slug.strip("_") or "x"


def default_prefix(file: str) -> str:
    """Prefijo de código derivado del nombre de archivo (mismo criterio en todo el motor)."""
    stem = Path(file).stem.split(".")[0]
    return f"bcrd.xls.{_slug(stem)}"


def _code_prefix(spec: ExtractionSpec) -> str:
    if spec.code_prefix:
        return spec.code_prefix
    return default_prefix(spec.file)


def _lineage(spec: ExtractionSpec) -> Lineage:
    url = spec.file if str(spec.file).startswith("http") else None
    return Lineage(source="BCRD", license=_LICENSE, fetched_at=date.today(), url=url)


def _forward_filled_years(grid: Grid, row: int, c0: int, c1: int) -> Dict[int, int]:
    """``col → year`` across [c0, c1), forward-filling sparse year headers."""
    col_year: Dict[int, int] = {}
    current: Optional[int] = None
    for c in range(c0, c1):
        y = parse_year(grid.cell(row, c))
        if y is not None:
            current = y
        if current is not None:
            col_year[c] = current
    return col_year


def _extract_period_rows(grid: Grid, spec: ExtractionSpec, lineage: Lineage,
                         prefix: str) -> List[Record]:
    end = spec.data_row_end if spec.data_row_end is not None else grid.nrows
    series = spec.series
    subtotal_re = re.compile(spec.subtotal_year_regex) if spec.subtotal_year_regex else None
    pcol = spec.month_col  # the within-year period column: months OR quarters
    out: List[Record] = []

    def subperiod(r: int) -> Optional[tuple]:
        """(kind, n) for the row's within-year period: ('M',1..12) or ('Q',1..4)."""
        if pcol is None:
            return None
        cell = grid.cell(r, pcol)
        m = parse_month(cell)
        if m is not None:
            return ("M", m)
        q = parse_quarter(cell)
        return ("Q", q) if q is not None else None

    def emit(year: int, sub: Optional[tuple], r: int) -> None:
        if sub and sub[0] == "Q":
            period = format_period(year, None, sub[1])
        elif sub and sub[0] == "M" and spec.day_col is not None:
            # Serie DIARIA: la planilla trae `Año | Mes | Día` y el día es parte del
            # período, no una medición. Sin esto los días de un mes colapsan en `YYYY-MM`
            # y el upsert deja uno arbitrario.
            dia = coerce_num(grid.cell(r, spec.day_col))
            period = (format_period(year, sub[1], day=int(dia)) if dia is not None
                      else format_period(year, sub[1]))
        else:
            period = format_period(year, sub[1] if sub else None)
        for s in series:
            out.append(Record(
                series=f"{prefix}.{s.code}" if not s.code.startswith(prefix) else s.code,
                period=period, value=coerce_num(grid.cell(r, s.value_col)),
                lineage=lineage, unit=s.unit,
            ))

    if subtotal_re is not None:
        # Year revealed by a trailing subtotal row ("Promedio 2007") or a bare-year
        # row ("2018"); buffer the block's months/quarters and stamp them on the year.
        buffer: List[tuple[int, tuple]] = []  # (row, sub)
        last_year: Optional[int] = None
        for r in range(spec.data_row_start, end):
            sub = subperiod(r)
            if sub is None:  # not a data period → maybe a year marker
                label = " ".join(
                    normalize_label(grid.cell(r, c)) for c in range(0, (pcol or 0) + 2)
                )
                m = subtotal_re.search(label)
                year = int(m.group(1)) if m else parse_year(grid.cell(r, pcol)) if pcol is not None else None
                if year is not None and buffer:
                    for br, bsub in buffer:
                        emit(year, bsub, br)
                    last_year = year
                    buffer = []
                continue
            buffer.append((r, sub))
        # A still-open final block (latest year, no subtotal yet): infer +1.
        if buffer and last_year is not None and len(buffer) <= 12:
            for br, bsub in buffer:
                emit(last_year + 1, bsub, br)
        return out

    # Sparse year column, forward-filled down the rows. With no period column this
    # is the *annual* case: each row that carries its own year is one obs.
    annual = pcol is None
    current_year: Optional[int] = None
    for r in range(spec.data_row_start, end):
        row_year = parse_year(grid.cell(r, spec.year_col)) if spec.year_col is not None else None
        if row_year is not None:
            current_year = row_year
        if annual:
            if row_year is None:  # header / blank / sub-total row → skip
                continue
            emit(row_year, None, r)
            continue
        sub = subperiod(r)
        if sub is None or current_year is None:
            continue
        emit(current_year, sub, r)
    return out


def _extract_matrix(grid: Grid, spec: ExtractionSpec, lineage: Lineage,
                    prefix: str) -> List[Record]:
    """Transpose of period_rows: periods across a header row, series down the rows."""
    c0 = spec.value_col_start or 0
    c1 = spec.value_col_end if spec.value_col_end is not None else grid.ncols
    label_col = spec.label_col if spec.label_col is not None else 0
    col_year = _forward_filled_years(grid, spec.period_header_row, c0, c1)
    # Optional sub-period row: quarter or month per column.
    col_sub: Dict[int, tuple] = {}
    # ¿Este cuadro publica el ACUMULADO del año en vez del flujo del trimestre? Lo declara el
    # propio encabezado (`E-J` = enero-junio, frente a `A-J` = abril-junio), y hay que
    # arrastrarlo al código de la serie: el acumulado y el flujo comparten sujeto, unidad y
    # período, y sin el calificador quien agrupe por el nombre de la serie sumaría los dos.
    acumulado = False
    if spec.subperiod_header_row is not None:
        for c in range(c0, c1):
            cell = grid.cell(spec.subperiod_header_row, c)
            q = parse_quarter(cell)
            if q is not None:
                col_sub[c] = ("Q", q)
                acumulado = acumulado or es_trimestre_acumulado(cell)
                continue
            m = parse_month(cell)
            if m is not None:
                col_sub[c] = ("M", m)

    # La dimensión de CONCEPTO: no divide el año, distingue magnitudes dentro de él. Va al
    # CÓDIGO de la serie, que es donde el sujeto tiene que viajar — no al período.
    col_dim: Dict[int, str] = {}
    if spec.dimension_header_row is not None:
        for c in range(c0, c1):
            etiqueta = _slug(str(grid.cell(spec.dimension_header_row, c) or ""))
            if etiqueta:
                col_dim[c] = etiqueta

    def period_for(year: int, c: int) -> str:
        sub = col_sub.get(c)
        if sub and sub[0] == "Q":
            return format_period(year, None, sub[1])
        if sub and sub[0] == "M":
            return format_period(year, sub[1])
        return format_period(year, None)

    end = spec.data_row_end if spec.data_row_end is not None else grid.nrows
    out: List[Record] = []
    seen: Dict[str, int] = {}
    # Ruta jerárquica por INDENTACIÓN: {columna_del_rótulo: texto}. Las planillas de
    # estadística anidan por sangría —ACTIVOS (c2) › Inversión de Cartera (c3) › Títulos
    # de deuda (c4) › Autoridades Monetarias (c5)— y la MISMA hoja se repite bajo padres
    # distintos. Antes se descartaban las filas de sección (no traen números) y las hojas
    # repetidas se desempataban por número de fila (`otros_sectores_r27`): se tiraba
    # justamente el dato que las distinguía. Ahora la sección se conserva como ancestro y
    # el código se compone con la ruta, que es un nombre y no una coordenada.
    ancestors: Dict[int, str] = {}
    # Jerarquía por MARCADOR DE TEXTO: cuando la planilla no usa sangría, el BCRD marca
    # los agregados con el signo de la identidad contable —"(+) Consumo Final" y debajo,
    # sin marca, "Consumo Privado" / "Consumo Público"—. La sangría no los separa (todo
    # en la misma columna), pero el marcador sí dice quién es agregado y quién componente.
    marker_group: Dict[int, str] = {}
    # Ancestros por NUMERACIÓN de esquema, para las planillas que anidan con "1.1." en vez
    # de con sangría. Se lleva por profundidad, no por columna: en piianual_6 las 538 filas
    # están todas en la misma columna y lo único que las ordena es el número.
    outline: Dict[int, str] = {}
    outline_last: Optional[str] = None
    # Tercer mecanismo: una fila SIN cifras abre un bloque y sigue calificando a las filas
    # de su MISMA columna (en pib_gasto, "Ponderación" encabeza un segundo bloque que
    # repite los mismos componentes). Se lleva aparte de `ancestors` a propósito: allá una
    # fila de la misma columna reemplaza a la anterior, y acá tiene que persistir.
    section_scope: Dict[int, str] = {}
    for r in range(spec.data_row_start, end):
        raw, raw_col = None, label_col
        for c in range(0, max(label_col + 1, c0)):
            cell = grid.cell(r, c)
            if isinstance(cell, str) and cell.strip():
                raw, raw_col = cell, c
                break
        if raw is None:
            continue
        name = str(raw).strip()
        if not name:
            continue
        marked = _MARKER_RE.match(name)
        if marked:
            name = name[marked.end():].strip() or name
        numbered = _OUTLINE_RE.match(name)
        if numbered:
            depth = _outline_depth(numbered.group("num"))
            name = name[numbered.end():].strip() or name
            outline = {d: lab for d, lab in outline.items() if d < depth}
            outline[depth] = name
            outline_last = name
        elif outline and outline_last is not None and name != outline_last:
            pass    # fila sin numerar: cuelga del último numerado (se arma abajo)
        # Al bajar o mantener nivel, los ancestros más profundos dejan de aplicar.
        ancestors = {col: lab for col, lab in ancestors.items() if col < raw_col}
        ancestors[raw_col] = name
        if marked:
            marker_group[raw_col] = name          # abre grupo para las filas sin marca
            marker_group = {c: g for c, g in marker_group.items() if c <= raw_col}
        # Una fila de sección (sin cifras) NO produce serie, pero YA quedó registrada como
        # ancestro: esa es la corrección de fondo — antes se descartaba y con ella se
        # perdía la única información que distinguía a las hojas repetidas.
        if not any(isinstance(grid.cell(r, c), (int, float)) for c in range(c0, c1)):
            section_scope = {c: g for c, g in section_scope.items() if c < raw_col}
            section_scope[raw_col] = name
            marker_group = {c: g for c, g in marker_group.items() if c < raw_col}
            continue
        path = [ancestors[col] for col in sorted(ancestors) if col < raw_col]
        scope = section_scope.get(raw_col)
        if scope and scope != name:
            path.append(scope)
        if outline:
            # La ruta de esquema reemplaza a la de columnas cuando existe: es más precisa
            # (la sangría puede ser uniforme; el número nunca miente sobre el nivel).
            path = [outline[d] for d in sorted(outline) if outline[d] != name]
        group = marker_group.get(raw_col)
        if group and not marked and group != name:
            path.append(group)                    # componente: cuelga de su agregado
        path.append(name)
        code = ".".join(_slug(part) for part in path if _slug(part))
        if acumulado and code:
            code = f"{code}_acumulado"
        if code in seen:  # ruta repetida (raro): desempate final por fila, nunca fusionar
            code = f"{code}_r{r}"
        seen[code] = r
        for c in range(c0, c1):
            year = col_year.get(c)
            if year is None:
                continue
            dim = col_dim.get(c)
            out.append(Record(
                series=f"{prefix}.{code}.{dim}" if dim else f"{prefix}.{code}",
                period=period_for(year, c),
                value=coerce_num(grid.cell(r, c)), lineage=lineage, unit=spec.unit,
            ))
    return out


def _extract_cross_tab(grid: Grid, spec: ExtractionSpec, lineage: Lineage,
                       prefix: str) -> List[Record]:
    c0 = spec.value_col_start or 0
    c1 = spec.value_col_end if spec.value_col_end is not None else grid.ncols
    col_year = _forward_filled_years(grid, spec.year_header_row, c0, c1)
    # Forward-fill the optional super-header (ACTIVOS/RESERVAS) across the value
    # range; columns before any super-label (the pre-methodology block) get none.
    col_super: Dict[int, str] = {}
    if spec.super_header_row is not None:
        current = ""
        for c in range(c0, c1):
            lab = _clean_label(grid.cell(spec.super_header_row, c))
            if lab:
                current = lab
            if current:
                col_super[c] = current
    col_metric: Dict[int, str] = {}
    if spec.metric_header_row is not None:
        for c in range(c0, c1):
            label = _clean_label(grid.cell(spec.metric_header_row, c))
            if label:
                sup = col_super.get(c, "")
                col_metric[c] = f"{sup} {label}".strip() if sup else label
    end = spec.data_row_end if spec.data_row_end is not None else grid.nrows
    out: List[Record] = []
    for r in range(spec.data_row_start, end):
        month = parse_month(grid.cell(r, spec.month_col)) if spec.month_col is not None else None
        if month is None:
            continue
        for c in range(c0, c1):
            year = col_year.get(c)
            if year is None:
                continue
            metric = col_metric.get(c, "valor")
            code = f"{prefix}.{_slug(metric)}"
            out.append(Record(
                series=code, period=format_period(year, month),
                value=coerce_num(grid.cell(r, c)), lineage=lineage, unit=spec.unit,
            ))
    return out


def _extract_year_blocks(grid: Grid, spec: ExtractionSpec, lineage: Lineage,
                         prefix: str) -> List[Record]:
    """Bloques apilados por año: ``1978`` en fila suelta, sus doce meses debajo.

    Las SERIES son las columnas (Total mensual, acumulado, tasa de crecimiento…) y el
    PERÍODO se arma con el año del bloque vigente más el mes de la fila. Antes este layout
    caía en ``matrix`` y cada mes repetido se volvía una serie —`enero`, `enero_r35`—:
    no era un problema de nombre sino de forma, el archivo entero salía mal armado.
    """
    c0 = spec.value_col_start or 0
    c1 = spec.value_col_end if spec.value_col_end is not None else grid.ncols

    # Nombre de cada columna: super-encabezado ("Total") + métrica ("Mensual").
    # El super-encabezado puede venir PARTIDO en varias filas: Excel envuelve el texto de
    # una celda ancha y el resto cae en la fila de abajo («Bebidas Alcohólicas y» +
    # «y Tabaco»). Se unen las filas desde `super_header_row` hasta la métrica, y recién
    # después se rellena hacia la derecha — al revés, cada fila rellenaría por su cuenta y
    # una columna heredaría el nombre de su vecina.
    col_super: Dict[int, str] = {}
    if spec.super_header_row is not None:
        fin = spec.metric_header_row if spec.metric_header_row is not None else spec.super_header_row + 1
        propio: Dict[int, str] = {}
        for c in range(c0, c1):
            partes = [_clean_label(grid.cell(r, c)) or ""
                      for r in range(spec.super_header_row, max(fin, spec.super_header_row + 1))]
            # Una parte que YA está contenida en lo acumulado no se repite: la fila de
            # abajo a veces reproduce la cola del rótulo entero («Bebidas Alcohólicas y
            # Tabaco» + «y Tabaco»), y concatenar a ciegas produce nombres duplicados.
            junto = ""
            for x in partes:
                if x and x.lower() not in junto.lower():
                    junto = f"{junto} {x}".strip()
            if junto:
                propio[c] = junto
        current = ""
        for c in range(c0, c1):
            if propio.get(c):
                current = propio[c]
            if current:
                col_super[c] = current
    col_name: Dict[int, str] = {}
    for c in range(c0, c1):
        metric = ""
        if spec.metric_header_row is not None:
            metric = _clean_label(grid.cell(spec.metric_header_row, c)) or ""
        sup = col_super.get(c, "")
        name = f"{sup} {metric}".strip() if (sup and metric) else (metric or sup)
        if name:
            col_name[c] = name

    out: List[Record] = []
    year: Optional[int] = None
    month_col = spec.month_col if spec.month_col is not None else 0
    for r in range(spec.data_row_start or 0, grid.nrows):
        label_cell = grid.cell(r, month_col)
        month = parse_month(label_cell)
        if month is None:
            y = parse_year(label_cell)
            if y is not None:
                year = y      # cabecera del bloque: cambia el año vigente
            continue
        if year is None:
            continue
        for c in range(c0, c1):
            col_label = col_name.get(c, "")
            if not col_label:
                continue
            out.append(Record(
                series=f"{prefix}.{_slug(col_label)}", period=format_period(year, month),
                value=coerce_num(grid.cell(r, c)), lineage=lineage, unit=spec.unit,
            ))
    return out


def extract_records(workbook: Workbook, spec: ExtractionSpec) -> List[Record]:
    """Replay *spec* over *workbook* → ``Record``s (one per series × period)."""
    grid = workbook.grid(spec.sheet)
    lineage = _lineage(spec)
    prefix = _code_prefix(spec)
    if spec.data_row_start is None:  # a spec may omit it; start from the top
        spec.data_row_start = 0
    if spec.orientation == "year_blocks":
        return _extract_year_blocks(grid, spec, lineage, prefix)
    if spec.orientation == "cross_tab":
        return _extract_cross_tab(grid, spec, lineage, prefix)
    if spec.orientation == "matrix":
        return _extract_matrix(grid, spec, lineage, prefix)
    return _extract_period_rows(grid, spec, lineage, prefix)
