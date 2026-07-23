"""Dos defectos que descartaban dato en silencio.

1) Multi-hoja: el motor elegía UNA hoja (la más densa) y tiraba el resto. En 5 de los 23
   archivos canónicos eso descartaba 15 hojas — y en ``tasa_desocupacion.xls`` la más
   densa es "Anual 1960-1990", así que se ingería la historia vieja y se perdía la serie
   moderna.
2) Jerarquía por MARCADOR: cuando la planilla no usa sangría, el BCRD marca los agregados
   con el signo de la identidad contable ("(+) Consumo Final") y debajo, sin marca, sus
   componentes. Sin leer el marcador, componentes de agregados distintos colisionaban.
"""
from shared.data.bcrd_excel.extract import extract_records
from shared.data.bcrd_excel.inference import data_sheets, infer_spec
from shared.data.bcrd_excel.workbook import Grid, Workbook


def _sheet(name, rows):
    return Grid(name=name, rows=rows)


def _annual(n=6, base=100.0):
    head = ["Componentes"] + [1990 + i for i in range(n)]
    return head, [base + i for i in range(n)]


# ─── Multi-hoja ───────────────────────────────────────────────────────


def test_all_data_sheets_are_kept_not_just_the_densest():
    head, vals = _annual()
    rica = _sheet("Anual 1960-1990", [head] + [["Serie A"] + vals] * 4)
    # Hoja CHICA pero legítima: una sola serie. El umbral es bajo a propósito — dejarla
    # afuera repetiría el defecto que esta función corrige.
    pobre = _sheet("Anual 1991-2016", [head] + [["Serie B"] + vals] * 2)
    wb = Workbook(path="x.xls", grids=[rica, pobre])
    nombres = [g.name for g in data_sheets(wb)]
    assert "Anual 1960-1990" in nombres and "Anual 1991-2016" in nombres


def test_cover_and_notes_sheets_are_excluded():
    """Portadas y notas no deben entrar: se filtran por densidad numérica."""
    head, vals = _annual()
    datos = _sheet("Datos", [head] + [["Serie"] + vals] * 5)
    portada = _sheet("Notas", [["Fuente: BCRD"], ["Nota metodológica"]])
    wb = Workbook(path="x.xls", grids=[datos, portada])
    assert [g.name for g in data_sheets(wb)] == ["Datos"]


def test_a_single_sheet_workbook_is_unchanged():
    head, vals = _annual()
    wb = Workbook(path="x.xls", grids=[_sheet("Única", [head] + [["Serie"] + vals] * 4)])
    assert len(data_sheets(wb)) == 1


# ─── Jerarquía por marcador de texto ──────────────────────────────────


def _pib_like():
    head = ["Componentes"] + [1990 + i for i in range(6)]
    rows = [head]
    for label in ("(+) Consumo Final", "Consumo Privado", "Consumo Público",
                  "(+) Formación Bruta de capital", "Variación de Existencias",
                  "(=) Producto Interno Bruto"):
        rows.append([label] + [100.0 + len(label)] * 6)
    return Workbook(path="pib_gasto.xls", grids=[_sheet("Valores", rows)])


def test_components_hang_from_their_marked_aggregate():
    wb = _pib_like()
    recs = extract_records(wb, infer_spec(wb, "pib_gasto.xls"))
    codes = {r.series.split("pib_gasto.")[-1] for r in recs}
    assert "consumo_final.consumo_privado" in codes
    assert "consumo_final.consumo_publico" in codes
    assert "formacion_bruta_de_capital.variacion_de_existencias" in codes


def test_the_marker_itself_is_not_part_of_the_name():
    wb = _pib_like()
    recs = extract_records(wb, infer_spec(wb, "pib_gasto.xls"))
    codes = {r.series.split("pib_gasto.")[-1] for r in recs}
    assert "consumo_final" in codes           # sin "(+)" ni rastro del signo
    assert not any("+" in c or "(" in c for c in codes)


def test_two_components_with_the_same_name_stay_distinct():
    """El caso que motivó todo: sin el marcador, dos 'Otros' de agregados distintos
    colisionaban y se desempataban por número de fila."""
    head = ["Componentes"] + [1990 + i for i in range(6)]
    rows = [head,
            ["(+) Exportaciones"] + [1.0] * 6,
            ["Otros"] + [2.0] * 6,
            ["(-) Importaciones"] + [3.0] * 6,
            ["Otros"] + [4.0] * 6]
    wb = Workbook(path="pib_gasto.xls", grids=[_sheet("V", rows)])
    recs = extract_records(wb, infer_spec(wb, "pib_gasto.xls"))
    codes = {r.series.split("pib_gasto.")[-1] for r in recs}
    assert "exportaciones.otros" in codes and "importaciones.otros" in codes
