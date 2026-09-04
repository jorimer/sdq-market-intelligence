"""El relleno del super-encabezado no puede pasarse del final del cuadro.

En `year_blocks` el rótulo de grupo viene una sola vez —Excel lo escribe en la celda
combinada de la izquierda— y se rellena hacia la derecha. El relleno no tenía freno: seguía
hasta `value_col_end`, que por defecto es el ANCHO DE LA HOJA. En `taap_pasivad.xlsx` la hoja
declara 256 columnas y el cuadro termina en la 14 («Interbancaria», un grupo sin métrica
propia): las 241 columnas vacías de la derecha heredaban ese nombre y emitían 27.715
observaciones nulas bajo el código de la tasa interbancaria — 29.325 filas donde había 1.610
observaciones reales.

No producía un conflicto de valores —son todas nulas y el upsert protege el valor real— así
que ningún criterio de conflicto lo veía. Lo delata la DENSIDAD: filas contra claves
distintas, ×18,21.

Y hay una segunda mitad: una columna con dato SUELTA a la derecha del cuadro, separada por
columnas en blanco, tampoco pertenece al último grupo. En `ipc_grupos_base_2019-2020.xls` la
columna 32 —diez valores sueltos, sin encabezado— heredaba «Bienes y Servicios Diversos».

Regla: una columna completamente en blanco —sin rótulo propio, sin métrica y sin dato— TERMINA
el alcance del grupo. Es la misma regla del separador vacío en `matrix`: un grupo no cruza una
columna que no existe.
"""
from typing import Any, List, Optional

from shared.data.bcrd_excel.extract import extract_records
from shared.data.bcrd_excel.spec import ExtractionSpec
from shared.data.bcrd_excel.workbook import Grid, Workbook

_ANCHO = 9  # el cuadro ocupa 1..3; 4..8 son el relleno de la hoja


def _grid(dato_suelto: bool = False):
    r_super: List[Any] = [None] * _ANCHO
    r_metr: List[Any] = [None] * _ANCHO
    r_super[1] = "Certificados"
    r_metr[1] = "0 a 30 días"
    r_metr[2] = "31 a 60 días"
    # Un grupo SIN métrica propia: es el caso de «Interbancaria», que vive en la fila de
    # super-encabezado y no tiene nada debajo.
    r_super[3] = "Interbancaria"
    filas: List[List[Any]] = [r_super, r_metr]
    v = 1.0
    for anio in (2017, 2018):
        filas.append([float(anio)] + [None] * (_ANCHO - 1))
        for mes in ("Enero", "Febrero"):
            fila: List[Any] = [mes] + [None] * (_ANCHO - 1)
            for c in (1, 2, 3):
                fila[c] = v
                v += 1
            if dato_suelto:
                fila[7] = 999.0   # columna suelta, tras cuatro columnas en blanco
            filas.append(fila)
    ruta: Optional[str] = None
    return Workbook(path=ruta, grids=[Grid(name="Pasivas", rows=filas)])  # type: ignore[arg-type]


def _spec():
    return ExtractionSpec(
        file="taap_pasivad.xlsx", sheet="Pasivas", orientation="year_blocks",
        data_row_start=2, month_col=0, super_header_row=0, metric_header_row=1,
        value_col_start=1, value_col_end=_ANCHO, code_prefix="p",
    )


def test_las_columnas_vacias_no_heredan_el_grupo():
    recs = extract_records(_grid(), _spec())
    inter = [r for r in recs if r.series == "p.interbancaria"]
    # Cuatro períodos (2017-01, 2017-02, 2018-01, 2018-02) y ni uno más: la columna 3 es la
    # ÚNICA que se llama así.
    assert len(inter) == 4, f"la interbancaria se emitió {len(inter)} veces, no 4"
    assert all(r.value is not None for r in inter)


def test_ninguna_serie_repite_serie_y_periodo():
    recs = extract_records(_grid(), _spec())
    claves = {(r.series, r.period) for r in recs}
    assert len(recs) == len(claves), (
        f"{len(recs)} filas para {len(claves)} claves distintas: hay columnas fantasma")


def test_un_dato_suelto_tras_columnas_en_blanco_no_es_del_ultimo_grupo():
    recs = extract_records(_grid(dato_suelto=True), _spec())
    sueltos = [r for r in recs if r.value == 999.0]
    assert not sueltos, (
        "una columna sin encabezado, separada del cuadro por columnas en blanco, se publicó "
        f"como {sorted({r.series for r in sueltos})}")
