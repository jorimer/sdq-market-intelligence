"""El año se arrastra hacia abajo SOLO cuando la celda está vacía.

Es como el BCRD publica casi todos sus cuadros —el año una vez por bloque, los meses
debajo— y para eso arrastrar es correcto. **Cuando la celda tiene algo que NO es un año,
heredar el anterior inventa una fecha**, y el daño es doble y silencioso: la observación se
estampa en el año equivocado, y ese año queda con dos registros para el mismo mes.

**No es hipotético.** En el cuadro V.1 «Valores subastados del Banco Central» las filas de
enero a noviembre de 2005 llevan `01` en la columna de año —una errata del emisor; el orden
las fija sin ambigüedad entre «2004 Dic» y «2005 Dic»—. Con el arrastre se estampaban como
2004, que en ese archivo viene vacío: **once meses de 2005 perdidos y once de 2004
duplicados**, 132 pares con dos registros y 99 en desacuerdo. Nada fallaba.

El cambio se MIDIÓ antes de hacerlo sobre los 33 archivos habilitados: cero filas cambian de
comportamiento. Doce usan este camino y ninguna tiene una celda de año no vacía que no
parsee; las otras veintiuna no lo usan.
"""
from typing import List

from shared.data.bcrd_excel.extract import extract_records
from shared.data.bcrd_excel.inference import infer_spec
from shared.data.bcrd_excel.workbook import Grid, Workbook

_MESES = ("Ene", "Feb", "Mar", "Abr", "May", "Jun",
          "Jul", "Ago", "Sep", "Oct", "Nov", "Dic")


def _hoja(anio_de_las_filas_intrusas: object) -> Workbook:
    """Dos años de datos donde el SEGUNDO llega con su celda de año adulterada.

    2020 entero, después once filas cuyo año dice lo que se le pase, y `2021 Dic` cerrando
    — que es exactamente la forma del cuadro V.1.
    """
    filas: List[list] = [["Cuadro de prueba"], [], ["Año", "Mes", "Tasa"]]
    for mes in _MESES:
        filas.append([2020, mes, None])          # el año real viene VACÍO de valores
    for mes in _MESES[:11]:
        filas.append([anio_de_las_filas_intrusas, mes, 7.5])
    filas.append([2021, "Dic", 7.5])
    return Workbook(path=None, grids=[Grid(name="V1", rows=filas)])  # type: ignore[arg-type]


def _leer(wb: Workbook) -> tuple:
    spec = infer_spec(wb, "cuadro_de_prueba.xlsx")
    declaradas: List[str] = []
    recs = extract_records(wb, spec, declaradas)
    return recs, declaradas


def test_una_celda_de_ano_ILEGIBLE_no_hereda_el_ano_anterior() -> None:
    """El caso real: `01` donde va 2021. Las once filas se descartan y se declaran."""
    recs, declaradas = _leer(_hoja("01"))
    periodos = [r.period for r in recs]
    assert not [p for p in periodos if p.startswith("2020-") and periodos.count(p) > 1], (
        "las filas de año ilegible heredaron 2020 y duplicaron sus meses")
    assert len(declaradas) == 11, f"se declararon {len(declaradas)} filas y son once"
    assert all("'01'" in d for d in declaradas), "la declaración no dice QUÉ decía la celda"
    assert any("no es un año" in d for d in declaradas)


def test_una_celda_VACIA_sigue_heredando() -> None: 
    """El contraejemplo que impide 'arreglar' esto rompiendo el caso normal.

    Si el arrastre dejara de funcionar para celdas vacías, este test cae — y con él la forma
    en que el BCRD publica casi todos sus cuadros.
    """
    filas: List[list] = [["Cuadro de prueba"], [], ["Año", "Mes", "Tasa"]]
    filas.append([2020, "Ene", 1.0])
    for mes in _MESES[1:]:
        filas.append([None, mes, 1.0])           # el año solo en la primera fila
    wb = Workbook(path=None, grids=[Grid(name="V1", rows=filas)])  # type: ignore[arg-type]
    recs, declaradas = _leer(wb)
    periodos = {r.period for r in recs}
    assert periodos == {f"2020-{m:02d}" for m in range(1, 13)}, sorted(periodos)
    assert not declaradas, "una celda vacía no es una brecha: es la forma normal del cuadro"


def test_un_ano_LEGIBLE_se_usa_aunque_venga_como_texto() -> None:
    """No se descarta por el tipo de la celda, sino por no poder leer un año."""
    recs, declaradas = _leer(_hoja("2021"))
    assert not declaradas
    assert {r.period for r in recs if r.period.startswith("2021")} == {
        f"2021-{m:02d}" for m in range(1, 13)}


def test_la_brecha_se_DECLARA_y_no_solo_se_descarta() -> None:
    """Descartar en silencio sería el mismo defecto con otra cara: el archivo se vería
    completo. La fila descartada viaja al reporte de ingesta."""
    _recs, declaradas = _leer(_hoja("01"))
    assert declaradas, "se descartaron filas sin dejar rastro"
    for d in declaradas:
        assert "fila " in d and "se descarta" in d
