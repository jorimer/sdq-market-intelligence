"""Una serie DIARIA necesita un período con día, y el trimestre se escribe de dos maneras.

**Dos defectos del mismo archivo.** `TASA_DOLAR_REFERENCIA_MC.xlsx` publica el tipo de cambio
en siete cortes. Dos fallaban:

* `PromTrimestral` y `FPTrimestral` rotulan el trimestre con los meses COMPLETOS
  —`Enero-Marzo`, `Abril-Junio`— y el mapa solo tenía las formas abreviadas (`ene-mar`). Sin
  trimestre, las cuatro filas de cada año colapsaban en el año: 367 valores en conflicto.
* `Diaria` es una serie diaria de verdad —columnas `Año | Mes | Día`— y el período no tenía
  día: los ~22 días hábiles de cada mes colapsaban en `YYYY-MM` y sobrevivía uno arbitrario.
  19.680 valores en conflicto, y de paso la columna `Día` se persistía como si fuera una
  medición (valores 2, 3, 4, 7…).

El día es la cuarta forma de período de la plataforma, junto a `YYYY`, `YYYY-Qn` y `YYYY-MM`.
"""
import pytest

from shared.data.bcrd_excel.periods import (
    es_trimestre_acumulado, format_period, parse_quarter,
)


@pytest.mark.parametrize("etiqueta,trimestre", [
    ("Enero-Marzo", 1), ("Abril-Junio", 2),
    ("Julio-Septiembre", 3), ("Octubre-Diciembre", 4),
    ("enero - marzo", 1), ("Octubre-Diciembre ", 4),
])
def test_el_trimestre_tambien_se_escribe_con_los_meses_completos(etiqueta, trimestre):
    assert parse_quarter(etiqueta) == trimestre


@pytest.mark.parametrize("etiqueta,trimestre", [
    ("Enero-Junio", 2), ("Enero-Septiembre", 3), ("Enero-Diciembre", 4),
])
def test_el_acumulado_largo_tambien(etiqueta, trimestre):
    """`Enero-Diciembre` es el acumulado del año; `Octubre-Diciembre` es el cuarto
    trimestre. Los dos dan 4, y solo el primero es acumulado."""
    assert parse_quarter(etiqueta) == trimestre
    assert es_trimestre_acumulado(etiqueta) is True


def test_octubre_diciembre_NO_es_acumulado():
    assert es_trimestre_acumulado("Octubre-Diciembre") is False


# ── El día ───────────────────────────────────────────────────────────────────────

def test_un_periodo_con_dia_se_formatea_iso():
    assert format_period(2026, 3, day=7) == "2026-03-07"
    assert format_period(2026, 12, day=31) == "2026-12-31"


def test_las_otras_tres_formas_no_cambian():
    """El día es una forma NUEVA, no un reemplazo: nada de lo que ya se persistió puede
    cambiar de etiqueta."""
    assert format_period(2026, None) == "2026"
    assert format_period(2026, None, 2) == "2026-Q2"
    assert format_period(2026, 3) == "2026-03"


# ── `Año | Trimestre | valores`: el año en una columna, el trimestre en otra ──────

def test_una_planilla_de_ano_y_trimestre_da_trimestres():
    """El corte trimestral del tipo de cambio pone el año en una columna y el trimestre en
    la de al lado. La inferencia solo miraba la del año, así que las cuatro filas de cada
    año caían en el año: 367 valores en conflicto entre `PromTrimestral` y `FPTrimestral`."""
    from shared.data.bcrd_excel.extract import extract_records
    from shared.data.bcrd_excel.inference import infer_spec
    from shared.data.bcrd_excel.workbook import Grid, Workbook

    filas = [["Tasas de Cambio"], [], ["Año", "Trimestre", "Compra", "Venta"]]
    v = 3.0
    for anio in range(1985, 1998):
        for t in ("Enero-Marzo", "Abril-Junio", "Julio-Septiembre", "Octubre-Diciembre"):
            filas.append([anio, t, v, v + 0.02])
            v += 0.01
    wb = Workbook(path=None, grids=[Grid(name="PromTrimestral", rows=filas)])
    sp = infer_spec(wb, "TASA_DOLAR_REFERENCIA_MC.xlsx")
    sp.code_prefix = "p"
    recs = extract_records(wb, sp)
    compra = [r for r in recs if r.series.endswith(".compra")]
    periodos = sorted(str(r.period) for r in compra)
    assert len(periodos) == len(set(periodos)), "los trimestres colapsan en el año"
    assert periodos[0] == "1985-Q1" and periodos[-1] == "1997-Q4"
    assert len(periodos) == 13 * 4
