"""Apply an :class:`ExtractionSpec` to a workbook → normalized ``Record``s.

This layer is purely deterministic: given a (correct) spec it always produces the
same records, so it is exhaustively unit-tested against the three calibration
files. All the heterogeneity lives upstream in the spec; here we only replay it.
"""
from __future__ import annotations

import re
from dataclasses import replace
from datetime import date
from pathlib import Path
from typing import Dict, List, Optional

from shared.data.base_client import Record
from shared.data.lineage import Lineage

from .inference import _axis_year
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
from .units import unidad_declarada_en_el_rotulo
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
                         prefix: str, sin_anio: Optional[List[str]] = None) -> List[Record]:
    end = spec.data_row_end if spec.data_row_end is not None else grid.nrows
    series = spec.series
    subtotal_re = re.compile(spec.subtotal_year_regex) if spec.subtotal_year_regex else None
    pcol = spec.month_col  # the within-year period column: months OR quarters
    out: List[Record] = []
    if sin_anio is None:
        sin_anio = []

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
    #
    # EL ARRASTRE SOLO VALE PARA UNA CELDA VACÍA. Es la forma en que el BCRD publica casi
    # todos sus cuadros —el año una vez por bloque y los meses debajo— y para eso el arrastre
    # es correcto. Cuando la celda tiene ALGO que no es un año, heredar el anterior inventa
    # una fecha, y el daño es doble y silencioso: la observación se estampa en el año
    # equivocado y ese año queda duplicado.
    #
    # Pasó, y se midió: en el cuadro V.1 de valores subastados las filas de enero a noviembre
    # de 2005 llevan «01» en la columna de año. Con el arrastre se estampaban como 2004 —que
    # en ese archivo viene vacío— perdiendo once meses de 2005 y duplicando once de 2004.
    #
    # El cambio se midió antes de hacerlo, sobre los 33 archivos habilitados: **cero filas**
    # cambian de comportamiento. Doce usan este camino y ninguna tiene una celda de año no
    # vacía que no parsee; las otras veintiuna no lo usan.
    annual = pcol is None
    current_year: Optional[int] = None
    for r in range(spec.data_row_start, end):
        celda_anio = grid.cell(r, spec.year_col) if spec.year_col is not None else None
        row_year = parse_year(celda_anio) if spec.year_col is not None else None
        if row_year is not None:
            current_year = row_year
        elif celda_anio is not None and str(celda_anio).strip():
            # Hay algo escrito y no es un año: el año de esta fila es DESCONOCIDO. No se
            # hereda —eso la mandaría a una fecha inventada— y la fila se declara.
            sin_anio.append(
                f"fila {r}: la columna de año dice {str(celda_anio).strip()!r}, que no es un "
                "año; la fila se descarta en vez de heredar el año anterior")
            continue
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


def _titulo_de_bloque(grid: Grid, period_row: Optional[int], col: int) -> str:
    """Título del cuadro que empieza en *col*: el texto de la fila de arriba del encabezado.

    Se busca desde esa columna hacia la izquierda porque el título suele estar en la celda
    del arranque del bloque, pero Excel a veces lo deja una o dos columnas antes.
    """
    if period_row is None or period_row == 0:
        return ""
    for c in range(col, max(-1, col - 3), -1):
        v = grid.cell(period_row - 1, c)
        if isinstance(v, str) and v.strip():
            return _slug(v)
    return ""


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

    # Un cuadro puede traer OTRO al lado, con su propio eje de años: la hoja de llegadas
    # pone los años completos y, tras una columna vacía, el corte «enero-julio». Los años se
    # repiten con valores distintos, y sin decir a qué bloque pertenece cada columna las dos
    # series compiten por la misma clave. Cuando el eje REINICIA —un año que ya se vio—
    # empieza un bloque nuevo, y su título (la fila de arriba del encabezado) va al código.
    # El PRIMER bloque no se califica: es el cuadro principal y su título no aporta.
    # Una columna SIN NINGÚN dato es un separador entre cuadros, no un período: emitir sus
    # nulos fabricaría una observación vacía que compite con la real por la misma clave.
    fin_datos = spec.data_row_end if spec.data_row_end is not None else grid.nrows
    vacias = {c for c in range(c0, c1)
              if all(coerce_num(grid.cell(r, c)) is None
                     for r in range(spec.data_row_start or 0, min(fin_datos, grid.nrows)))}

    col_bloque: Dict[int, str] = {}
    vistos_anio: set = set()
    bloque_actual = ""
    ultimo_declarado: Optional[int] = None
    cruzo_separador = False
    for c in range(c0, c1):
        # El reinicio se detecta sobre el año DECLARADO en el encabezado, no sobre el
        # rellenado hacia la derecha: con el rellenado, la columna separadora hereda el
        # último año y dispara el corte una columna antes del cuadro nuevo.
        declarado = (_axis_year(grid.cell(spec.period_header_row, c))
                     if spec.period_header_row is not None else None)
        if declarado is None:
            cruzo_separador = cruzo_separador or c in vacias
        else:
            # Un año REPETIDO en columnas contiguas NO es un reinicio: así se escribe una
            # matriz trimestral, con el año encima de cada uno de sus cuatro trimestres. El
            # eje reinicia cuando vuelve un año ya visto que NO es el de la columna anterior,
            # o cuando vuelve después de una columna separadora — que es donde termina un
            # cuadro y empieza otro.
            reinicia = declarado in vistos_anio and (declarado != ultimo_declarado
                                                     or cruzo_separador)
            if reinicia:
                bloque_actual = (_titulo_de_bloque(grid, spec.period_header_row, c)
                                 or f"bloque_c{c}")
                vistos_anio = {declarado}
            else:
                vistos_anio.add(declarado)
            ultimo_declarado = declarado
            cruzo_separador = False
        if bloque_actual:
            col_bloque[c] = bloque_actual

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
    #: base repetida → filas que la usan; y de qué tramo de `out` salió cada fila, para
    #: poder volver sobre la primera cuando se descubre que el rótulo no era único.
    repetidos: Dict[str, List[int]] = {}
    codigo_de_fila: Dict[int, str] = {}
    indices_de_fila: Dict[int, tuple] = {}
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
        # Un rótulo repetido dentro del cuadro no identifica a nadie —tampoco al primero
        # que lo tomó—. En la balanza de pagos «Nacionales» y «Zonas Francas» cuelgan de
        # «Exportaciones» y de «Importaciones» sin numeración ni sangría que las ordene:
        # marcando solo a la segunda, la primera quedaba como `balanza_de_bienes.nacionales`
        # —nacionales ¿de qué?— al lado de una que sí decía «importaciones». Se desempatan
        # LAS DOS y el nombrado semántico les da a ambas su padre. Misma regla que en
        # `year_blocks` y en `period_rows`.
        base = code
        if base in seen:
            repetidos.setdefault(base, [seen[base]]).append(r)
            code = f"{code}_r{r}"
        else:
            seen[base] = r
        codigo_de_fila[r] = code
        desde = len(out)
        for c in range(c0, c1):
            year = col_year.get(c)
            if year is None or c in vacias:
                continue
            sufijos = [x for x in (col_bloque.get(c), col_dim.get(c)) if x]
            out.append(Record(
                series=".".join([f"{prefix}.{code}", *sufijos]),
                period=period_for(year, c),
                value=coerce_num(grid.cell(r, c)), lineage=lineage,
                unit=_unidad(" ".join([*path, *sufijos]), spec),
            ))
        indices_de_fila[r] = (desde, len(out))
    # Segunda pasada: la PRIMERA aparición de un código repetido también se desempata. Se
    # hace al final porque solo al terminar de recorrer se sabe si el rótulo era único.
    for base, filas in repetidos.items():
        primera = filas[0]
        desde, hasta = indices_de_fila.get(primera, (0, 0))
        for i in range(desde, hasta):
            out[i] = replace(out[i], series=out[i].series.replace(
                f"{prefix}.{base}", f"{prefix}.{base}_r{primera}", 1))
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
                value=coerce_num(grid.cell(r, c)), lineage=lineage,
                unit=_unidad(metric, spec),
            ))
    return out


def _unidad(rotulo: str, spec: ExtractionSpec) -> Optional[str]:
    """La unidad de la serie: lo que declara su ROTULO antes que el título de la hoja.

    `period_rows` resuelve esto al inferir el spec (`_series_from_columns`), pero las otras
    tres orientaciones le ponían a TODA columna la unidad de hoja. En el IPC por grupos eso
    dejaba las doce columnas de «Var. %» con `unit='Índice'` — y `infer_nature`, obedeciendo
    su regla correcta de que la unidad manda, las clasificaba `index`. Es el mismo guard que
    ya existía en un motor y faltaba en los otros.
    """
    return unidad_declarada_en_el_rotulo(rotulo) or spec.unit


def _columna_con_contenido(grid: Grid, spec: ExtractionSpec, col: int) -> bool:
    """¿La columna existe en el cuadro, o es relleno de la hoja?

    Existe si tiene métrica propia o si trae algún número en la región de datos. Una hoja de
    Excel declara muchas más columnas de las que usa, y sin este freno el rótulo del último
    grupo se rellenaba hasta el borde declarado.
    """
    if spec.metric_header_row is not None and _clean_label(
            grid.cell(spec.metric_header_row, col)):
        return True
    for r in range(spec.data_row_start or 0, grid.nrows):
        if coerce_num(grid.cell(r, col)) is not None:
            return True
    return False


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
        # Un rótulo de grupo que se REPITE en la fila no identifica a nadie —tampoco al
        # primero que lo tomó—. En las llegadas de pasajeros el encabezado alterna
        # `Total | Tasa de Crecimiento | Dominicanos | Tasa de Crecimiento`: las dos tasas
        # producían el MISMO código y colisionaban en silencio, 4.555 valores resueltos por
        # orden de lectura. Se califica con el último grupo ÚNICO que las precede, que es lo
        # que las distingue. Misma regla que `_grupo_a_la_izquierda` en `period_rows`: se
        # califica a TODOS los que comparten el rótulo, no solo a los que llegan después.
        cuantos: Dict[str, int] = {}
        for etiqueta in propio.values():
            cuantos[etiqueta.lower()] = cuantos.get(etiqueta.lower(), 0) + 1
        # Una columna COMPLETAMENTE en blanco —sin rótulo propio, sin métrica y sin dato—
        # termina el alcance del grupo. El relleno no tenía freno y seguía hasta
        # `value_col_end`, que por defecto es el ANCHO DE LA HOJA: en `taap_pasivad.xlsx` la
        # hoja declara 256 columnas, el cuadro termina en la 14 («Interbancaria», un grupo
        # sin métrica propia) y las 241 columnas vacías de la derecha heredaban ese nombre —
        # 27.715 observaciones nulas bajo el código de la tasa interbancaria. No producía
        # conflicto de valores (son nulas, y el upsert protege el valor real), así que
        # ningún criterio de conflicto lo veía: lo delata la densidad, ×18,21 filas por
        # clave. Es la misma regla del separador vacío en `matrix`: un grupo no cruza una
        # columna que no existe. Con eso, una columna con dato SUELTA a la derecha —la 32
        # del IPC por grupos, diez valores sin encabezado— tampoco hereda el último grupo.
        current = ""
        ultimo_unico = ""
        for c in range(c0, c1):
            rotulo = propio.get(c)
            if rotulo:
                if cuantos[rotulo.lower()] > 1 and ultimo_unico:
                    current = f"{ultimo_unico} {rotulo}"
                else:
                    current = rotulo
                    ultimo_unico = rotulo
            elif not _columna_con_contenido(grid, spec, c):
                current = ""
                ultimo_unico = ""
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
                value=coerce_num(grid.cell(r, c)), lineage=lineage,
                unit=_unidad(col_label, spec),
            ))
    return out


def extract_records(workbook: Workbook, spec: ExtractionSpec,
                    sin_anio: Optional[List[str]] = None) -> List[Record]:
    """Replay *spec* over *workbook* → ``Record``s (one per series × period).

    `sin_anio`, si se pasa, recibe una línea por cada fila DESCARTADA porque su columna de
    año tenía algo que no es un año. Se devuelve en vez de solo registrarse en el log: una
    brecha que solo va al log no la ve nadie, y el motor ya tiene un canal de avisos que
    llega al reporte de validación.
    """
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
    return _extract_period_rows(grid, spec, lineage, prefix, sin_anio)
