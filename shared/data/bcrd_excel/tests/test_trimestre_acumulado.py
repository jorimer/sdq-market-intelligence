"""Un trimestre ACUMULADO sigue siendo un trimestre — y tiene que decir que lo es.

**El defecto.** El BCRD publica cada cuadro trimestral dos veces: el flujo del trimestre, con
columnas `E-M · A-J · J-S · O-D`, y el acumulado del año, con `E-M · E-J · E-S · E-D` (enero
a marzo / junio / septiembre / diciembre). El mapa de trimestres tenía los cuatro primeros y
ninguno de los acumulados, así que tres de cada cuatro columnas del cuadro acumulado no
resolvían trimestre y caían al AÑO: las tres competían por la misma clave `(serie, 2018)` y
el dedupe «último gana» dejaba una arbitraria. En el PIB por sector de origen eso eran 1.660
duplicados con valores distintos y 163 series con períodos mezclados.

**Y el acumulado tiene que decir que es acumulado.** Con el arreglo, el `2019-Q2` del cuadro
acumulado vale enero-junio, no abril-junio: mismo sujeto, misma unidad y mismo período que la
serie de flujo. Si solo lo distinguiera el segmento de hoja del código, alguien que agrupe por
el nombre de la serie sumaría el flujo con el acumulado. El calificador viaja en el CÓDIGO, y
lo decide el propio encabezado del cuadro — no el nombre del archivo ni una lista a mano.
"""
import pytest

from shared.data.bcrd_excel.extract import extract_records
from shared.data.bcrd_excel.periods import es_trimestre_acumulado, parse_quarter
from shared.data.bcrd_excel.spec import ExtractionSpec
from shared.data.bcrd_excel.workbook import Grid, Workbook


@pytest.mark.parametrize("etiqueta,trimestre", [
    ("E-M", 1), ("E-J", 2), ("E-S", 3), ("E-D", 4),
    ("Ene-Jun", 2), ("Ene-Sep", 3), ("Ene-Dic", 4),
])
def test_los_rotulos_acumulados_resuelven_trimestre(etiqueta, trimestre):
    assert parse_quarter(etiqueta) == trimestre


@pytest.mark.parametrize("etiqueta,trimestre", [
    ("E-M", 1), ("A-J", 2), ("J-S", 3), ("O-D", 4),
])
def test_los_rotulos_de_flujo_siguen_igual(etiqueta, trimestre):
    """Lo que ya andaba no se toca: el cuadro de flujo se lee como siempre."""
    assert parse_quarter(etiqueta) == trimestre


@pytest.mark.parametrize("etiqueta,acumulado", [
    ("E-J", True), ("E-S", True), ("E-D", True), ("Ene-Dic", True),
    ("A-J", False), ("J-S", False), ("O-D", False),
    # Enero-marzo es el primer trimestre en los DOS cuadros y vale lo mismo en ambos:
    # no alcanza para decidir, así que no se declara acumulado por sí solo.
    ("E-M", False),
])
def test_se_reconoce_cual_rotulo_es_acumulado(etiqueta, acumulado):
    assert es_trimestre_acumulado(etiqueta) is acumulado


def _hoja(subperiodos):
    """Un cuadro matriz mínimo: años en r0, subperíodos en r1, una serie en r2."""
    return Grid(name="H", rows=[
        ["AÑOS", 2018, None, None, None],
        [None, *subperiodos],
        ["Agropecuario", 10.0, 20.0, 30.0, 40.0],
    ])


def _spec():
    return ExtractionSpec(
        file="f.xlsx", sheet="H", orientation="matrix", data_row_start=2,
        period_header_row=0, subperiod_header_row=1, label_col=0,
        value_col_start=1, value_col_end=5, code_prefix="p",
    )


def test_el_cuadro_acumulado_da_cuatro_trimestres_y_no_colapsa_en_el_ano():
    recs = extract_records(Workbook(path=None, grids=[_hoja(["E-M", "E-J", "E-S", "E-D"])]),
                           _spec())
    periodos = sorted(str(r.period) for r in recs)
    assert periodos == ["2018-Q1", "2018-Q2", "2018-Q3", "2018-Q4"]
    assert len({r.series for r in recs}) == 1


def test_la_serie_acumulada_lo_DICE_en_su_codigo():
    recs = extract_records(Workbook(path=None, grids=[_hoja(["E-M", "E-J", "E-S", "E-D"])]),
                           _spec())
    codigo = {r.series for r in recs}.pop()
    assert codigo.endswith("_acumulado"), codigo


def test_la_serie_de_FLUJO_no_lleva_el_calificador():
    recs = extract_records(Workbook(path=None, grids=[_hoja(["E-M", "A-J", "J-S", "O-D"])]),
                           _spec())
    codigo = {r.series for r in recs}.pop()
    assert not codigo.endswith("_acumulado"), codigo
    assert sorted(str(r.period) for r in recs) == ["2018-Q1", "2018-Q2", "2018-Q3", "2018-Q4"]


def test_el_valor_acumulado_CRECE_dentro_del_ano():
    """La prueba de que se leyó el cuadro acumulado y no el de flujo: enero-junio contiene a
    enero-marzo, así que Q2 ≥ Q1 por construcción."""
    recs = extract_records(Workbook(path=None, grids=[_hoja(["E-M", "E-J", "E-S", "E-D"])]),
                           _spec())
    v = {str(r.period): r.value for r in recs}
    assert v["2018-Q1"] < v["2018-Q2"] < v["2018-Q3"] < v["2018-Q4"]


# ── El calificador sobrevive al renombrado semántico ─────────────────────────────

def test_el_renombrado_semantico_conserva_el_calificador(monkeypatch):
    """El nombre semántico REEMPLAZA la hoja del código, así que se llevaba puesto el
    `_acumulado`: 96 de las 163 series acumuladas del PIB por origen volvían indistinguibles
    de las de flujo. Lo que el cuadro declara sobre su período no puede depender de si al
    modelo le tocó renombrar esa fila."""
    from shared.data.bcrd_excel import engine
    from shared.data.base_client import Record
    from shared.data.lineage import Lineage
    from datetime import date

    lin = Lineage(source="BCRD", license="x", fetched_at=date.today())
    records = [
        Record(series="bcrd.xls.f.hoja.agropecuario_acumulado_r46", period="2019-Q2",
               value=1.0, lineage=lin),
        Record(series="bcrd.xls.f.hoja.agropecuario_r46", period="2019-Q2",
               value=1.0, lineage=lin),
    ]
    monkeypatch.setattr(engine, "name_ambiguous_rows",
                        lambda grid, rows, client=None: {46: "Ponderación > Agropecuario"})
    wb = Workbook(path=None, grids=[Grid(name="hoja", rows=[["x"]])])
    spec = ExtractionSpec(file="f", sheet="hoja", orientation="matrix", data_row_start=0,
                          code_prefix="bcrd.xls.f.hoja")
    salida = {r.series for r in engine._resolve_ambiguous_names(wb, spec, records)}
    assert "bcrd.xls.f.hoja.ponderacion.agropecuario_acumulado" in salida, salida
    assert "bcrd.xls.f.hoja.ponderacion.agropecuario" in salida, salida
