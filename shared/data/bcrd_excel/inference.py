"""Heuristic structural inference — grid → :class:`ExtractionSpec` + confidence.

This resolves the common BCRD layouts without a model call. It scores its own
output; the engine routes anything below a confidence threshold to the Claude
interpreter. The signals it reads:

* the **month axis** — the column (period_rows) or row-region with the densest run
  of Spanish month names;
* the **year strategy** — a sparse year column aligned to the data rows, or
  trailing ``"Promedio YYYY"`` subtotal rows that close each block;
* **cross-tab** — a header row carrying many years spread across columns while a
  column carries months (periods on both axes);
* **value columns** — numeric-dense columns, named from the header rows above.
"""
from __future__ import annotations

import re
from typing import List, Optional, Set, Tuple

from .periods import coerce_num, normalize_label, parse_month, parse_quarter, parse_year
from .spec import ExtractionSpec, SeriesSpec
from .units import sheet_unit, split_header_unit, unidad_declarada_en_el_rotulo
from .workbook import Grid, Workbook


def _hoja(name: str) -> str:
    """El último nivel de un rótulo compuesto: «Serie Original · Índice» → `indice`."""
    return _slug(str(name).split(" · ")[-1])


def _series_from_columns(grid: Grid, value_cols: List[int], data_row0: int,
                         sheet_default: Optional[str]) -> List[SeriesSpec]:
    """``SeriesSpec`` por columna, CAPTURANDO la unidad que el emisor declaró.

    La unidad por-columna (``PIB nominal (Millones de RD$)``) manda; si la columna no la
    trae, cae a la unidad de hoja (``sheet_default``). Sin ninguna, ``None`` — la serie
    quedará en naturaleza ``unknown`` honesta, nunca inventada. Códigos duplicados se
    desempatan por columna, jamás se fusionan."""
    crudos = []
    for c in value_cols:
        name, unit = split_header_unit(
            _header_name(grid, c, data_row0, cols_de_valor=set(value_cols)))
        # El paréntesis manda; después, lo que el rótulo declara con palabras; recién al
        # final el título de la hoja. Antes el título pisaba a la columna: «Índice de
        # Precios al Consumidor» convertía en `index` a toda variación porcentual del
        # cuadro.
        crudos.append((c, name, unit or unidad_declarada_en_el_rotulo(name)))

    # Un nombre que resulta ser COMPARTIDO no nombra a nadie — tampoco al primero que lo
    # tomó. En el IPC por quintiles la primera columna de tasa es la del quintil 1 y se
    # quedaba con «tasa de inflación» a secas, que es tan ambiguo como los `_c5` de las
    # otras cuatro. Por eso el desempate se decide sobre el CONJUNTO y califica a todos los
    # que comparten un nombre, no solo a los que llegan después.
    # La colisión se mide sobre la HOJA del rótulo —el último nivel, «Interanual»— y no
    # sobre el nombre entero. En el IMAE la columna interanual de la Serie Original trae dos
    # filas de encabezado propias («Variación porcentual» + «Interanual») y las de las otras
    # dos series traen una sola: mirando el nombre completo, la primera parecía única y se
    # quedaba sin decir de qué cuadro era, mientras sus dos hermanas sí lo decían. El sujeto
    # viaja con el número para las tres o para ninguna.
    cuantos: dict[str, int] = {}
    for _c, name, _u in crudos:
        cuantos[_hoja(name)] = cuantos.get(_hoja(name), 0) + 1

    # Qué calificador desempata a los que comparten nombre. Hay dos candidatos —el grupo de
    # ARRIBA (filas superiores del encabezado, rellenadas desde la izquierda: así escribe
    # Excel una celda combinada) y el vecino de la IZQUIERDA— y la elección no se puede
    # tomar columna por columna: un calificador que sale IGUAL para todas las que colisionan
    # no identifica a ninguna. Con dos niveles el vecino ES el grupo (el índice del quintil
    # está justo a la izquierda de su tasa, y arriba las cinco dicen «Tasa de Inflación»);
    # con TRES el vecino es otra métrica del mismo cuadro, y el IMAE salía con el «Promedio
    # 12 meses» de la Serie Original llamándose `acumulada_promedio_12_meses`.
    primera = min(value_cols) if value_cols else 0
    arriba = {c: _grupo_por_encima(grid, c, data_row0, name, primera)
              for c, name, _u in crudos}
    columnas_de: dict[str, List[int]] = {}
    for c, name, _u in crudos:
        columnas_de.setdefault(_hoja(name), []).append(c)
    usa_el_de_arriba = {
        base: (len(cols) > 1
               and all(arriba.get(c) for c in cols)
               and len({arriba[c] for c in cols}) == len(cols))
        for base, cols in columnas_de.items()
    }

    series: List[SeriesSpec] = []
    usados: set[str] = set()
    for c, name, unit in crudos:
        code = _slug(name)
        if cuantos[_hoja(name)] > 1:
            grupo = (arriba[c] if usa_el_de_arriba.get(_hoja(name))
                     else _grupo_a_la_izquierda(grid, c, data_row0, name))
            if grupo and _slug(f"{grupo} {name}") not in usados:
                # Un nivel que el nombre ya dice no se repite: la columna de «Respecto al
                # período anterior» tiene «Variación porcentual» en su propia fila Y en la
                # del grupo, y concatenar a ciegas produce
                # `..._variacion_porcentual_variacion_porcentual_...`.
                niveles = [n for n in grupo.split(" · ")
                           if _slug(n) not in _slug(name).split("_" * 2)
                           and _slug(n) not in _slug(name)]
                grupo = " · ".join(niveles)
            if grupo and _slug(f"{grupo} {name}") not in usados:
                name = f"{grupo} · {name}"
                code = _slug(name)
        # La unidad se decide con el nombre YA COMPLETO: el calificador es parte del rótulo
        # y suele ser el que declara la magnitud —«Variación porcentual (%)» está en el
        # nivel de grupo, no en el de la columna—. Decidirla antes dejaba nueve columnas de
        # variación del IMAE con la unidad de hoja, «Índice».
        limpio, unidad_del_parentesis = split_header_unit(name)
        name = limpio or name
        # …y si el rótulo propio no dice la magnitud, la dice el GRUPO: en el IPC
        # subyacente las columnas se llaman «Acumulada» e «Interanual» a secas y lo que
        # declara que son porcentajes está una fila más arriba, en «Inflación Subyacente».
        # Solo para la UNIDAD: el nombre no se toca, porque calificar todos los nombres del
        # corpus renombraría series ya persistidas sin necesidad.
        unidad = (unit or unidad_del_parentesis
                  or unidad_declarada_en_el_rotulo(name)
                  or unidad_declarada_en_el_rotulo(arriba.get(c) or "")
                  or sheet_default)
        if code in usados:
            code = f"{code}_c{c}"
        usados.add(code)
        series.append(SeriesSpec(code=code, name=name, unit=unidad, value_col=c))
    return series


#: Cuántas filas del encabezado se miran hacia arriba buscando el grupo.
_FILAS_DE_ENCABEZADO = 6


def _grupo_por_encima(grid: Grid, value_col: int, data_row0: int, propio: str,
                      primera_col: int = 0) -> Optional[str]:
    """La cadena de grupos que cuelga sobre la columna, de arriba hacia abajo.

    Se lee como Excel la escribe: el rótulo de un grupo vive en la celda combinada más a la
    izquierda de su tramo, así que para cada fila del encabezado se toma la celda con texto
    más cercana a la izquierda (incluida la propia). El rodeo no pasa de *primera_col* —la
    primera columna de valores del cuadro—, que es lo que separa un encabezado de grupo del
    TÍTULO de la hoja: el título vive en la columna 0, a la izquierda de los ejes, y
    arrastrarlo bautizaría cada serie con el nombre del documento.
    """
    inicio = max(0, data_row0 - _FILAS_DE_ENCABEZADO)

    def _texto(r: int, c: int) -> Optional[str]:
        return _texto_de_rotulo(grid, r, c)

    filas_propias = [r for r in range(inicio, data_row0) if _texto(r, value_col)]
    if not filas_propias:
        return None
    tope = filas_propias[-1]

    niveles: List[str] = []
    for r in range(inicio, tope):
        for c in range(value_col, primera_col - 1, -1):
            txt = _texto(r, c)
            if txt:
                if txt.lower() != propio.lower() and txt not in niveles:
                    niveles.append(txt)
                break
    return " · ".join(niveles) or None


#: Cuántas columnas a la izquierda se busca el encabezado del GRUPO. Dos alcanza para el
#: patrón que motiva esto —índice, tasa, índice, tasa…— y no tanto como para arrastrar el
#: rótulo de un bloque ajeno.
_COLS_HACIA_LA_IZQUIERDA = 2


def _grupo_a_la_izquierda(grid: Grid, value_col: int, data_row0: int,
                          propio: str) -> Optional[str]:
    """El encabezado del GRUPO al que pertenece la columna, buscado hacia la izquierda.

    Por qué existe. En el IPC por quintiles el encabezado alterna «Quintil 1», «Tasa de
    Inflación», «Quintil 2», «Tasa de Inflación»…: las cinco columnas de tasa se llaman
    IGUAL, y el nombre que las distingue —el quintil— está en la columna del índice, a la
    izquierda. Sin esto el desempate era el ÍNDICE DE COLUMNA (`tasa_de_inflacion_c5`), un
    código que no dice de qué quintil es la tasa. Se persistieron dieciocho series así, en
    quintiles, en el IPC por región y en el IMAE.

    Se verificó contra el dato antes de escribir esto: cada una de las cinco tasas coincide
    EXACTAMENTE —error 0,00000 pp sobre setenta puntos— con la variación mensual del índice
    del quintil que este mapeo le asigna. No era una serie inservible: era una serie mal
    nombrada, y la diferencia entre descartarla y nombrarla son cinco series reales.

    Devuelve ``None`` si a la izquierda no hay un rótulo DISTINTO del propio: repetir el
    mismo texto no desambigua nada, y ahí sí corresponde caer a la coordenada.
    """
    filas = range(max(0, data_row0 - 6), data_row0)
    propio_l = (propio or "").strip().lower()
    for c in range(value_col - 1, max(-1, value_col - 1 - _COLS_HACIA_LA_IZQUIERDA), -1):
        for r in filas:
            v = grid.cell(r, c)
            if v is None or isinstance(v, (int, float)):
                continue
            txt = str(v).strip()
            if txt and txt.lower() != propio_l and txt.lower() not in propio_l:
                return txt
    return None

_SUBTOTAL_RE = r"promedio\s+(\d{4})"
_SCAN_HEADER_ROWS = 12  # header region to mine for names / year rows


def sheet_numeric_density(g: Grid) -> int:
    """Celdas numéricas en la región de cabecera — proxy de "esta hoja trae datos"."""
    return sum(
        1
        for r in range(min(60, g.nrows))
        for c in range(min(40, g.ncols))
        if isinstance(g.cell(r, c), (int, float))
    )


def data_sheets(wb: Workbook, *, min_cells: int = 10, min_ratio: float = 0.03) -> List[Grid]:
    """TODAS las hojas con datos, no solo la más densa.

    Un libro del BCRD suele traer varios cortes de la misma estadística en hojas separadas
    (llegadas: No Residentes / Residentes / Total; desempleo: cuatro rangos de años).
    Quedarse con una sola descarta el resto EN SILENCIO — y no siempre se queda con la
    mejor: en ``tasa_desocupacion.xls`` la hoja más densa es "Anual 1960-1990", así que se
    ingería la historia vieja y se tiraba la serie moderna.

    Se excluyen portadas y notas por densidad: hace falta un mínimo absoluto de celdas
    numéricas y una fracción de la hoja más rica. Los umbrales son BAJOS a propósito —
    una hoja legítima puede ser chica (una serie de doce años son doce celdas), y
    descartarla sería repetir el defecto que esta función viene a corregir."""
    scored = [(sheet_numeric_density(g), g) for g in wb.grids]
    if not scored:
        return []
    best = max(n for n, _ in scored)
    keep = [g for n, g in scored if n >= min_cells and n >= best * min_ratio]
    return keep or [max(scored, key=lambda t: t[0])[1]]


def _pick_sheet(wb: Workbook) -> Grid:
    """The sheet with the most numeric cells (the data sheet, not notes/cover)."""
    best, best_score = wb.grids[0], -1.0
    for g in wb.grids:
        n = sum(
            1
            for r in range(min(60, g.nrows))
            for c in range(min(40, g.ncols))
            if isinstance(g.cell(r, c), (int, float))
        )
        if n > best_score:
            best, best_score = g, n
    return best


def _month_column(grid: Grid) -> Tuple[Optional[int], int, int]:
    """Find the column richest in month names. Returns (col, first_row, count)."""
    best_col, best_count, best_first = None, 0, 0
    for c in range(min(6, grid.ncols)):
        rows = [r for r in range(grid.nrows) if parse_month(grid.cell(r, c)) is not None]
        if len(rows) > best_count:
            best_col, best_count, best_first = c, len(rows), rows[0]
    return best_col, best_first, best_count


def _standalone_year_rows(grid: Grid, month_col: Optional[int]) -> List[int]:
    """Filas que traen SOLO un año en la columna de rótulos: cabecera de bloque anual.

    Es la firma de las planillas del BCRD que apilan un bloque por año (llegadas de
    pasajeros, 1978-2026): ``1978`` en su propia fila y debajo los doce meses. El año no
    está en un encabezado de columna, así que las detecciones habituales no lo ven."""
    if month_col is None:
        return []
    out: List[int] = []
    for r in range(grid.nrows):
        if parse_month(grid.cell(r, month_col)) is not None:
            continue
        if _axis_year(grid.cell(r, month_col)) is not None:
            out.append(r)
    return out


def _axis_year(value) -> Optional[int]:
    """Years for *axis detection* — stricter than ``parse_year`` so a year buried in
    a subtitle ("Bases 1999 y 2010") or a range ("1991-2013") is NOT counted as a
    period axis. Accepts a numeric year cell, or a string that *is* a year (allowing
    a trailing footnote like "2008 3/")."""
    if isinstance(value, (int, float)):
        y = int(value)
        return y if 1900 <= y <= 2100 else None
    token = normalize_label(value)
    # La nota al pie es un marcador FINAL («2008 3/»). Recortar cualquier `NN/` en cualquier
    # posición convertía una FECHA en un año: `31/12/2009` quedaba en `2009`, y una fila de
    # fechas de corte pasaba por fila de años. En la posición de inversión internacional el
    # cuadro trae las dos —años arriba, fechas debajo— y el motor elegía la de fechas: el año
    # de cada columna salía CORRIDO, con `Transacciones Netas` de 2011 etiquetado 2010.
    token = re.sub(r"\s+\d+\s*/\s*$", "", token).strip()   # nota al pie final: "2008 3/"
    # Y los marcadores con que el BCRD señala un año PRELIMINAR o revisado: "2011*",
    # "2013**", "2021 (p)". Se toleraba solo la nota con barra, así que esos años caían del
    # eje temporal, el rango de columnas se cortaba en el último año "limpio" y las columnas
    # siguientes —con dato— no se leían nunca: `bpagos` perdía 2011-2013 y `lleg_total` el
    # año en curso. En `pib_origen_2018` casi todos los años están marcados `(p)`, así que la
    # heurística no encontraba eje, devolvía confianza 0,0 y el trabajo caía en el modelo,
    # que a su vez truncaba por su vista previa recortada. Un rótulo no reconocido encadenó
    # los dos defectos.
    #
    # Se recorta SOLO al final, y el año sigue teniendo que ser todo lo que queda: un año
    # dentro de un subtítulo ("Bases 1999 y 2010") o de un rango ("1991-2013") no es un eje.
    token = re.sub(r"[\s*]*\(\s*[pe]+\s*\)\s*$", "", token).strip()   # "(p)" / "(e)"
    token = token.rstrip("* ").strip()                                # "2011*" / "2013 **"
    if re.fullmatch(r"(19|20)\d{2}", token):
        return int(token)
    return None


def periodos_sin_leer(grid: Grid, spec) -> List[Tuple[int, int]]:
    """Períodos que el ENCABEZADO declara y que el rango del spec deja afuera, con dato.

    Es el guard de un defecto que apareció dos veces el mismo día: un spec que corta el rango
    de columnas antes del último año publicado, y la serie sale corta sin error, sin hueco y
    sin marca — `PIB$_Trim_Acum` terminaba cinco años antes que sus hojas hermanas, y
    `bpagos`/`lleg_total` perdían sus últimos años porque el rótulo venía marcado preliminar.
    Las causas se arreglaron; esto es para que la próxima no sea invisible.

    **La regla NO es «hay números más allá del rango».** Un cuadro con dos bloques —niveles y
    después «Tasas de Crecimiento», con encabezados `92/91`— tiene números afuera y hace bien
    en no leerlos: ése fue el falso positivo de `pib_gasto.xls`. Se exige lo preciso: que no
    quede afuera una columna cuyo encabezado declara un PERÍODO **y** que además trae dato.

    Devuelve ``[(columna, año)]``; vacío cuando no hay nada que reclamar.
    """
    c1 = getattr(spec, "value_col_end", None)
    fila = getattr(spec, "period_header_row", None)
    if c1 is None or fila is None:
        return []
    r0 = getattr(spec, "data_row_start", None) or 0
    fuera: List[Tuple[int, int]] = []
    for c in range(c1, grid.ncols):
        anio = _axis_year(grid.cell(fila, c))
        if anio is None:
            continue
        if any(coerce_num(grid.cell(r, c)) is not None
               for r in range(r0, min(grid.nrows, r0 + 40))):
            fuera.append((c, anio))
    return fuera


#: Cómo rotula el emisor la columna del día. Se decide por el ENCABEZADO —que es donde el
#: emisor lo declara— y no por «la columna trae enteros de 1 a 31», que también describe a un
#: recuento de sucursales o a una edad.
_ROTULOS_DE_DIA = {"dia", "día", "day", "dias", "días"}


def _day_column(grid: Grid, month_col: int, data_row0: int) -> Optional[int]:
    """La columna del DÍA en una planilla diaria (`Año | Mes | Día`), o ``None``.

    Se exige rótulo Y contenido: el encabezado tiene que nombrarla, y sus valores tienen que
    ser días de calendario. Con el rótulo solo, un cuadro que se llame «Días de mora» pasaría
    por eje temporal; con el contenido solo, cualquier columna de enteros chicos lo haría.
    """
    for c in range(month_col + 1, min(grid.ncols, month_col + 3)):
        rotulado = any(normalize_label(grid.cell(r, c)) in _ROTULOS_DE_DIA
                       for r in range(max(0, data_row0 - 6), data_row0))
        if not rotulado:
            continue
        vals = [grid.cell(r, c) for r in range(data_row0, min(grid.nrows, data_row0 + 40))]
        nums = [v for v in vals if isinstance(v, (int, float))]
        if nums and all(1 <= int(v) <= 31 and float(v) == int(v) for v in nums):
            return c
    return None


#: Cuántas veces tiene que repetirse un rótulo para ser una DIMENSIÓN y no un nombre suelto.
#: La firma es la repetición: el mismo juego de conceptos vuelve bajo cada año.
_MIN_REPETICIONES_DIMENSION = 3


def _dimension_row(grid: Grid, r0: Optional[int], r1: int, c0: int, c1: int) -> Optional[int]:
    """Fila de CONCEPTOS bajo los años: `Saldo al inicio | Transacciones Netas | …`.

    No es un subperíodo —no divide el año— sino una dimensión de la serie: para cada año hay
    varias magnitudes distintas. Sin reconocerla, las columnas de un año caen todas en el
    mismo `(serie, año)` y el dedupe «último gana» deja una arbitraria: en la posición de
    inversión internacional eran 2.970 valores en conflicto, y el archivo publicaba una sexta
    parte de lo que trae.

    Se exige REPETICIÓN, que es lo que distingue una dimensión de un rótulo suelto: el mismo
    conjunto de conceptos vuelve bajo cada año. Y se exige que NO sean períodos: si lo fueran,
    los resolvería `_subperiod_row`, que es quien corresponde.
    """
    if r0 is None:
        return None
    for r in range(r0 + 1, min(r1, grid.nrows)):
        etiquetas = [str(grid.cell(r, c)).strip() for c in range(c0, min(c1, grid.ncols))
                     if isinstance(grid.cell(r, c), str) and str(grid.cell(r, c)).strip()]
        if len(etiquetas) < _MIN_REPETICIONES_DIMENSION * 2:
            continue
        if any(parse_quarter(e) is not None or parse_month(e) is not None for e in etiquetas):
            continue                      # es un subperíodo, no una dimensión
        repetidas = len(etiquetas) - len(set(etiquetas))
        if repetidas >= _MIN_REPETICIONES_DIMENSION:
            return r
    return None


def _row_is_mostly_numeric(grid: Grid, row: int, c0: int, c1: int) -> bool:
    """¿La fila trae mayoría de números? Entonces son DATOS, no rótulos.

    Un encabezado nombra; una fila de datos mide. Si se confunden, las series terminan
    llamándose como el valor de una celda — y el error no se ve en la extracción, se ve
    meses después cuando un informe cita `serie.280155040_6400002`."""
    filled = numeric = 0
    for c in range(c0, c1):
        cell = grid.cell(row, c)
        if cell in (None, ""):
            continue
        filled += 1
        if isinstance(cell, (int, float)):
            numeric += 1
        else:
            try:
                float(str(cell).replace(",", "").strip())
                numeric += 1
            except ValueError:
                pass
    return filled > 0 and numeric / filled > 0.5


def _year_header_row(grid: Grid) -> Tuple[Optional[int], int]:
    """Find a header row carrying several years across columns (cross-tab / matrix)."""
    best_row, best_count = None, 0
    for r in range(min(_SCAN_HEADER_ROWS, grid.nrows)):
        years = sum(1 for c in range(grid.ncols) if _axis_year(grid.cell(r, c)) is not None)
        if years > best_count:
            best_row, best_count = r, years
    return best_row, best_count


def _quarter_column(grid: Grid) -> Tuple[Optional[int], int, int]:
    """Column richest in quarter labels (I-IV / E-M / T1-T4). (col, first_row, count)."""
    best_col, best_count, best_first = None, 0, 0
    for c in range(min(4, grid.ncols)):
        rows = [r for r in range(grid.nrows) if parse_quarter(grid.cell(r, c)) is not None]
        if len(rows) > best_count:
            best_col, best_count, best_first = c, len(rows), rows[0]
    return best_col, best_first, best_count


def _has_year_markers(grid: Grid, col: int) -> bool:
    """True if year-marker rows exist in *col*: 'Promedio YYYY' or a bare year."""
    rx = re.compile(_SUBTOTAL_RE)
    for r in range(grid.nrows):
        label = " ".join(normalize_label(grid.cell(r, c)) for c in range(0, col + 2))
        if rx.search(label):
            return True
        cell = grid.cell(r, col)
        if parse_quarter(cell) is None and parse_month(cell) is None:
            v = cell if isinstance(cell, (int, float)) else None
            if v is not None and 1900 <= int(v) <= 2100:
                return True
    return False


def _year_column(grid: Grid) -> tuple[Optional[int], int, int]:
    """Column richest in years *down the rows* (annual period_rows). (col, count, first_row)."""
    best_col, best_count, best_first = None, 0, 0
    for c in range(min(4, grid.ncols)):
        rows = [r for r in range(grid.nrows) if _axis_year(grid.cell(r, c)) is not None]
        if len(rows) > best_count:
            best_col, best_count, best_first = c, len(rows), rows[0]
    return best_col, best_count, best_first


def _label_column(grid: Grid, value_col_start: int, row0: int, row1: int) -> Optional[int]:
    """Column left of the values richest in text labels (the series names, matrix)."""
    best_col, best_count = None, 0
    for c in range(0, max(1, value_col_start)):
        n = sum(
            1 for r in range(row0, min(row1, grid.nrows))
            if isinstance(grid.cell(r, c), str) and grid.cell(r, c).strip()
        )
        if n > best_count:
            best_col, best_count = c, n
    return best_col


def _subperiod_row(grid: Grid, period_row: int, data_row0: int, c0: int, c1: int) -> Optional[int]:
    """A row between the year header and the data whose cells parse as quarters/months."""
    for r in range(period_row + 1, max(period_row + 1, data_row0)):
        hits = sum(
            1 for c in range(c0, c1)
            if parse_quarter(grid.cell(r, c)) is not None or parse_month(grid.cell(r, c)) is not None
        )
        if hits >= 3:
            return r
    return None


def _has_subtotal_years(grid: Grid, month_col: int) -> bool:
    rx = re.compile(_SUBTOTAL_RE)
    for r in range(grid.nrows):
        label = " ".join(normalize_label(grid.cell(r, c)) for c in range(0, month_col + 2))
        if rx.search(label):
            return True
    return False


def _sparse_year_column(grid: Grid, month_col: int, row0: int) -> Optional[int]:
    """A column (left of months) with parseable years on some data rows."""
    for c in range(0, month_col + 1):
        hits = sum(
            1 for r in range(row0, min(row0 + 60, grid.nrows))
            if parse_year(grid.cell(r, c)) is not None
        )
        if hits >= 1:
            return c
    return None


#: Lo que el emisor escribe cuando NO hay dato. `coerce_num` ya los trata como vacío; acá
#: sirven para lo mismo del otro lado: una celda así tampoco bautiza una serie.
_MARCADORES_DE_VACIO = {"-", "--", "...", "n.d", "nd", "n/d", "na", "n/a"}

#: La fila de REFERENCIAS de línea con que el BCRD numera sus columnas para escribir sus
#: propias sumas: `(1)`, `(2)`, `(4)=(1 al 3)`. Es la fila más baja del encabezado, así que
#: era la que se tomaba como rótulo propio: la base monetaria salía con series llamadas
#: `me_9` y `valores_3`, y el número tapaba además la cadena de grupos de arriba.
_REFERENCIA_DE_LINEA = re.compile(r"^\(\s*\d+\s*\)\s*(=.*)?$")


def _es_referencia_de_linea(texto) -> bool:
    """¿La celda es un número de línea del emisor y no un nombre?"""
    return bool(_REFERENCIA_DE_LINEA.match(str(texto or "").strip()))


def _texto_de_rotulo(grid: Grid, r: int, c: int) -> Optional[str]:
    """El texto de una celda cuando SIRVE COMO RÓTULO, o ``None``.

    No lo son: los números, los marcadores de dato ausente y las referencias de línea. Es la
    misma regla en los dos buscadores de nombre —el propio y el del grupo—, en un solo lugar
    para que no se desincronicen."""
    v = grid.cell(r, c)
    if v is None or isinstance(v, (int, float)):
        return None
    txt = str(v).strip()
    if not txt or _es_referencia_de_linea(txt):
        return None
    if normalize_label(txt).rstrip(".") in _MARCADORES_DE_VACIO:
        return None
    return txt


def _header_name(grid: Grid, value_col: int, data_row0: int,
                 cols_de_valor: Optional[Set[int]] = None) -> str:
    """Build a series name from the non-empty header cells above a value column.

    La caída a ``value_col - 1`` existe porque a veces el rótulo se escribe una columna a la
    izquierda del dato. Pero solo se aplica cuando la columna del valor NO tiene rótulo
    propio en NINGUNA fila del encabezado: hacerlo fila por fila le roba el sub-encabezado a
    la serie vecina.

    El caso que lo destapó: en el IPC por quintiles el encabezado es «Quintil 2» en una fila
    y la celda de abajo está vacía, mientras la columna anterior —la tasa del quintil 1— dice
    «Inflación». La mezcla bautizaba `quintil_2_inflacion` a una columna que contiene un
    ÍNDICE. Un nombre así no es cosmético: dice que el número es una tasa cuando no lo es, y
    quien lo consuma después no tiene cómo saberlo.
    """
    filas = list(range(max(0, data_row0 - 6), data_row0))

    def _texto(r: int, c: int):
        # Un marcador de dato AUSENTE no es un rótulo, y un número de línea tampoco. En el
        # IPC subyacente las seis filas encima del primer dato son el final de un bloque de
        # cierres anuales y sus celdas dicen `-`: tres series quedaron llamándose `x`,
        # `x_c4` y `x_c5`. Ver `_texto_de_rotulo`.
        return _texto_de_rotulo(grid, r, c)

    propio = [c for c in (value_col,) if any(_texto(r, c) for r in filas)]
    cols = propio or [value_col - 1]

    # La ventana fija de seis filas no alcanza cuando entre el encabezado y el primer dato
    # hay un bloque intermedio. Se sigue buscando hacia arriba SOLO si la ventana no dio
    # ningún rótulo: donde hoy hay nombre no se toca nada — un renombrado masivo huerfanaría
    # las series ya persistidas, que se identifican por su código.
    if not any(_texto(r, c) for r in filas for c in (value_col, value_col - 1)):
        arriba = [r for r in range(data_row0 - 1, -1, -1)
                  if any(_texto(r, c) for c in (value_col, value_col - 1))]
        if arriba:
            filas = sorted(arriba[:3])
            propio = [c for c in (value_col,) if any(_texto(r, c) for r in filas)]
            cols = propio or [value_col - 1]
        else:
            # Nada en la columna ni en la de al lado. El rótulo puede estar más a la
            # izquierda cuando las columnas intermedias son EJES y no series: en
            # `tasa_ocupacion.xls` el cuadro es `Año | Semestre | valor` y el título vive en
            # la columna 0, así que la única serie del archivo salía llamándose `col2`.
            # El rodeo NO cruza otra columna de valor —robarle el rótulo al vecino es
            # exactamente lo que prohíbe `_header_name` desde el caso de los quintiles— y no
            # va más allá de cuatro columnas.
            ajenas = cols_de_valor or set()
            for c in range(value_col - 2, max(-1, value_col - 5), -1):
                if c < 0 or c in ajenas:
                    continue
                rotulada = [r for r in range(data_row0 - 1, -1, -1) if _texto(r, c)]
                if rotulada:
                    filas = sorted(rotulada[:2])
                    cols = [c]
                    break

    parts: List[str] = []
    for r in filas:
        for c in cols:
            txt = _texto(r, c)
            if txt and txt.lower() not in (p.lower() for p in parts):
                parts.append(txt)
                break
    return " · ".join(parts[-3:]) or f"col{value_col}"


def _value_columns(grid: Grid, month_col: int, data_row0: int) -> List[int]:
    """Columns after the month column that are numeric-dense over the data rows."""
    cols: List[int] = []
    sample_end = min(data_row0 + 80, grid.nrows)
    span = max(1, sample_end - data_row0)
    for c in range(month_col + 1, grid.ncols):
        numeric = sum(
            1 for r in range(data_row0, sample_end)
            if isinstance(grid.cell(r, c), (int, float))
        )
        if numeric / span >= 0.4:
            cols.append(c)
    return cols


def _slug(s: str) -> str:
    out = [ch if ch.isalnum() else "_" for ch in normalize_label(s)]
    slug = "".join(out)
    while "__" in slug:
        slug = slug.replace("__", "_")
    return slug.strip("_") or "x"


def infer_spec(wb: Workbook, file: str) -> ExtractionSpec:
    """Infer an :class:`ExtractionSpec` for *wb*, scoring its own confidence."""
    grid = _pick_sheet(wb)
    month_col, first_month_row, month_count = _month_column(grid)
    year_row, year_row_count = _year_header_row(grid)
    sh = wb.structure_hash()

    # Bloques por año: el año va en una FILA SUELTA y debajo cuelgan sus meses; las
    # columnas son las métricas. Se detecta ANTES que cross_tab porque comparte la señal
    # "muchos meses en una columna", pero acá los meses SE REPITEN (uno por bloque) y no
    # son series: son períodos. Sin esto, el extractor bautizaba una serie por cada mes
    # repetido (`enero`, `enero_r35`, `enero_r48`…) y el archivo entero salía mal armado.
    year_rows = _standalone_year_rows(grid, month_col)
    if month_col is not None and month_count >= 24 and len(year_rows) >= 3:
        metric_rows = [r for r in range(0, min(year_rows) if year_rows else 8)
                       if any(isinstance(grid.cell(r, c), str) and grid.cell(r, c).strip()
                              for c in range(month_col + 1, min(grid.ncols, month_col + 9)))]
        return ExtractionSpec(
            file=file, sheet=grid.name, orientation="year_blocks",
            data_row_start=min(year_rows), month_col=month_col,
            metric_header_row=metric_rows[-1] if metric_rows else None,
            # La PRIMERA fila del bloque de encabezado, no la penúltima: cuando el
            # rótulo se envuelve en dos filas, la penúltima es su CONTINUACIÓN («y
            # Tabaco») y tomarla dejaba a las doce columnas de índice del IPC por grupos
            # con el mismo nombre —doce series colapsadas en una, con doce valores por
            # mes y la última pisando a las anteriores—. `_extract_year_blocks` une desde
            # acá hasta la métrica.
            super_header_row=metric_rows[0] if len(metric_rows) >= 2 else None,
            value_col_start=month_col + 1, value_col_end=grid.ncols,
            # Tasas de interés, etc.: la unidad ("% nominal anual") va en el caption sobre
            # el primer bloque de año. Aplica a toda la hoja.
            unit=sheet_unit(grid, min(year_rows)),
            structure_hash=sh, confidence=0.85, method="heuristic",
            notes=(f"year_blocks: {len(year_rows)} años en fila suelta, "
                   f"{month_count} filas de mes"),
        )

    # Cross-tab: many years across a header row AND months down a column.
    if year_row_count >= 4 and month_col is not None and month_count >= 6:
        # value columns start just after the month column
        c0 = month_col + 1
        years_on_row = [c for c in range(c0, grid.ncols)
                        if _axis_year(grid.cell(year_row, c)) is not None]
        c1 = (max(years_on_row) + 3) if years_on_row else grid.ncols
        # Fila de métricas = la última de encabezado justo encima de los datos… SI EXISTE.
        # Cuando el encabezado de años está pegado a los datos (año en la fila 7, Enero en
        # la 8) NO hay fila de métricas: el archivo publica una sola magnitud. La fórmula
        # anterior —max(year_row+1, first_month_row-1)— devolvía igual una fila, y caía
        # sobre la PRIMERA DE DATOS: cada columna quedaba bautizada con el valor de esa
        # celda (`remesas_6.280155040_6400002`). No es que no supiéramos nombrar la serie;
        # estábamos leyendo un dato como si fuera un rótulo.
        # ``year_row`` es Optional en la firma pero acá ya está resuelto (la rama exige
    # year_row_count >= 4); se ancla en un int para que el checker lo siga.
        year_row_i = int(year_row or 0)
        metric_row = first_month_row - 1 if first_month_row - 1 > year_row_i else None
        # Cinturón y tirantes: si la fila candidata trae mayoría de números, no es un
        # encabezado por más que la geometría lo permita. Vale para cualquier planilla
        # futura con un layout que no anticipamos.
        if metric_row is not None and _row_is_mostly_numeric(grid, metric_row, c0, c1):
            metric_row = None
        # A super-header sits between the years and the metrics when that gap has
        # sparse text labels (e.g. ACTIVOS / RESERVAS over BRUTOS / BRUTAS / NETAS).
        # Sin fila de métricas tampoco hay hueco donde pueda vivir un super-encabezado.
        super_row = None
        for r in range(year_row_i + 1,
                       metric_row if metric_row is not None else year_row_i + 1):
            texts = sum(1 for c in range(c0, c1)
                        if isinstance(grid.cell(r, c), str) and grid.cell(r, c).strip())
            if texts >= 2:
                super_row = r
                break
        conf = min(0.9, 0.5 + 0.05 * year_row_count)
        return ExtractionSpec(
            file=file, sheet=grid.name, orientation="cross_tab",
            data_row_start=first_month_row, month_col=month_col,
            year_header_row=year_row, metric_header_row=metric_row,
            super_header_row=super_row,
            value_col_start=c0, value_col_end=c1,
            unit=sheet_unit(grid, year_row),
            structure_hash=sh, confidence=round(conf, 2), method="heuristic",
            notes=f"cross_tab: {year_row_count} años en fila {year_row}",
        )

    # period_rows
    if month_col is not None and month_count >= 6:
        subtotal = _has_subtotal_years(grid, month_col)
        year_col = None if subtotal else _sparse_year_column(grid, month_col, first_month_row)
        value_cols = _value_columns(grid, month_col, first_month_row)
        # La columna del DÍA es PERÍODO, no una serie. Sin esto nacía una serie cuyos
        # "valores" eran los días del calendario, y las columnas reales colapsaban todas
        # en `YYYY-MM` — una observación por mes elegida por orden de lectura.
        day_col = _day_column(grid, month_col, first_month_row)
        if day_col is not None:
            value_cols = [c for c in value_cols if c != day_col]
        # Distinct value columns must map to distinct series codes — never merge two
        # columns into one (e.g. "Acumulada" under both "Serie Original" and "Serie
        # Desestacionalizada"). Disambiguate slug collisions by column so the data
        # of two real series is never silently mixed. La unidad se captura del rótulo.
        series = _series_from_columns(grid, value_cols, first_month_row,
                                      sheet_unit(grid, first_month_row - 1))
        resolved = subtotal or year_col is not None
        conf = min(0.85, 0.5 + 0.03 * month_count) if (resolved and series) else 0.0
        return ExtractionSpec(
            file=file, sheet=grid.name, orientation="period_rows",
            data_row_start=first_month_row, month_col=month_col, year_col=year_col,
            day_col=day_col,
            subtotal_year_regex=_SUBTOTAL_RE if subtotal else None,
            series=series, structure_hash=sh,
            confidence=round(conf, 2) if resolved else 0.2,
            method="heuristic",
            notes=("subtotal-year" if subtotal else f"year_col={year_col}"),
        )

    # Matrix: many periods across a header row (years), series down the rows. Covers
    # national accounts, balance of payments, etc. — and the quarterly variants when
    # a sub-row carries E-M/A-J/J-S/O-D.
    if year_row_count >= 4:
        years_on_row = [c for c in range(grid.ncols)
                        if _axis_year(grid.cell(year_row, c)) is not None]
        c0, c1 = min(years_on_row), max(years_on_row) + 1
        label_col = _label_column(grid, c0, year_row + 1, grid.nrows)
        if label_col is not None:
            sub_row = _subperiod_row(grid, year_row, year_row + 4, c0, c1)
            # Si bajo los años no hay subperíodos sino CONCEPTOS que se repiten por año,
            # son una dimensión de la serie, no una división del año.
            dim_row = (None if sub_row is not None
                       else _dimension_row(grid, year_row, year_row + 4, c0, c1))
            freq = "quarterly" if sub_row is not None else "annual"
            data_start = (max(r for r in (sub_row, dim_row, year_row) if r is not None)) + 1
            conf = min(0.85, 0.5 + 0.03 * min(year_row_count, 12))
            return ExtractionSpec(
                file=file, sheet=grid.name, orientation="matrix",
                data_row_start=data_start, period_header_row=year_row,
                subperiod_header_row=sub_row, dimension_header_row=dim_row,
                label_col=label_col,
                value_col_start=c0, value_col_end=c1, frequency=freq,
                # Una matriz publica UNA magnitud (balanza en US$, saldos monetarios en
                # RD$): la unidad de la hoja aplica a todas sus filas. Se escanea solo la
                # zona de título, por encima de la fila de años.
                unit=sheet_unit(grid, year_row),
                structure_hash=sh, confidence=round(conf, 2), method="heuristic",
                notes=f"matrix {freq}: {year_row_count} períodos en fila {year_row}",
            )

    # Quarterly period_rows: quarters (I-IV / E-M) down a column, year revealed by
    # a "Promedio YYYY" or bare-year marker row (e.g. PIB / deflactor trimestral).
    qcol, first_q_row, q_count = _quarter_column(grid)
    if qcol is not None and q_count >= 4 and _has_year_markers(grid, qcol):
        value_cols = _value_columns(grid, qcol, first_q_row)
        series = _series_from_columns(grid, value_cols, first_q_row,
                                      sheet_unit(grid, first_q_row - 1))
        if series:
            return ExtractionSpec(
                file=file, sheet=grid.name, orientation="period_rows",
                data_row_start=first_q_row, month_col=qcol,
                # El vocabulario de esta columna es inglés y NO es una preferencia de
                # estilo: `mm_series.frequency` se sirve por la Data API que consume PMS, y
                # los otros módulos que la pueblan escriben inglés. Esta rama decía
                # "trimestral" mientras sus dos hermanas, tres líneas arriba y abajo, decían
                # "quarterly" y "annual". Lo vigila
                # `tests/test_vocabulario_de_frecuencia.py`, que lee el código con `ast`
                # porque el defecto vivía en UNA rama de tres.
                subtotal_year_regex=_SUBTOTAL_RE, series=series, frequency="quarterly",
                structure_hash=sh, confidence=round(min(0.82, 0.5 + 0.04 * q_count), 2),
                method="heuristic", notes="period_rows trimestral (marcador de año)",
            )

    # Annual period_rows: a column of years down the rows (no month axis).
    year_col, year_col_count, first_year_row = _year_column(grid)
    if year_col is not None and year_col_count >= 5 and year_col_count >= year_row_count:
        # ¿El año viene acompañado de una columna de TRIMESTRE? (`Año | Trimestre | …`, el
        # corte trimestral del tipo de cambio). Sin mirarla, las cuatro filas de cada año
        # caen todas en el año y compiten por la misma clave. `month_col` es la columna del
        # período DENTRO del año y acepta meses o trimestres — ver `_extract_period_rows`.
        qcol, first_q_row, q_count = _quarter_column(grid)
        if qcol is not None and qcol != year_col and q_count >= 4:
            value_cols = [c for c in _value_columns(grid, max(year_col, qcol), first_q_row)
                          if c not in (year_col, qcol)]
            series = _series_from_columns(grid, value_cols, first_q_row,
                                          sheet_unit(grid, first_q_row - 1))
            if series:
                conf = min(0.85, 0.5 + 0.02 * q_count)
                return ExtractionSpec(
                    file=file, sheet=grid.name, orientation="period_rows",
                    data_row_start=min(first_year_row, first_q_row),
                    month_col=qcol, year_col=year_col, series=series,
                    frequency="quarterly", structure_hash=sh,
                    confidence=round(conf, 2), method="heuristic",
                    notes=f"period_rows trimestral: year_col={year_col} quarter_col={qcol}",
                )
        value_cols = _value_columns(grid, year_col, first_year_row)
        series = _series_from_columns(grid, value_cols, first_year_row,
                                      sheet_unit(grid, first_year_row - 1))
        if series:
            conf = min(0.8, 0.45 + 0.02 * year_col_count)
            return ExtractionSpec(
                file=file, sheet=grid.name, orientation="period_rows",
                data_row_start=first_year_row, month_col=None, year_col=year_col,
                series=series, frequency="annual", structure_hash=sh,
                confidence=round(conf, 2), method="heuristic",
                notes=f"period_rows annual: year_col={year_col}",
            )

    # Unresolved — let the interpreter take it.
    return ExtractionSpec(
        file=file, sheet=grid.name, orientation="period_rows",
        data_row_start=0, structure_hash=sh, confidence=0.0, method="heuristic",
        notes="sin eje de período detectado",
    )
