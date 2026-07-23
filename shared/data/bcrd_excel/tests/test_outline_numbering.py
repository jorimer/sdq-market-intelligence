"""Jerarquía por NUMERACIÓN de esquema — el cuarto patrón, y el único determinista.

``piianual_6.xlsx`` trae 538 filas todas en la misma columna: no hay sangría que leer ni
marcador contable. Lo que las ordena es el número —"I. Activos" › "1. Inversión directa"
› "1.1. Participaciones de capital"— y eso no necesita modelo: la numeración ES la
jerarquía. El nombrado semántico había devuelto 0 de 66 filas acá; con esta regla salen
las 130 series con ruta completa y sin una sola llamada al modelo.
"""
from shared.data.bcrd_excel.extract import _outline_depth, extract_records
from shared.data.bcrd_excel.inference import infer_spec
from shared.data.bcrd_excel.workbook import Grid, Workbook


def _wb(labels):
    rows = [["Componentes"] + [2010 + i for i in range(6)]]
    for lab in labels:
        rows.append([lab] + [100.0 + len(lab)] * 6)
    return Workbook(path="pii.xlsx", grids=[Grid(name="PII", rows=rows)])


def _codes(labels):
    wb = _wb(labels)
    recs = extract_records(wb, infer_spec(wb, "piianual_6.xlsx"))
    return {r.series.split("piianual_6.")[-1] for r in recs}


def test_roman_is_the_outermost_level():
    assert _outline_depth("I") == 1 and _outline_depth("IV") == 1


def test_dotted_decimals_nest_by_component_count():
    assert _outline_depth("1") == 2
    assert _outline_depth("1.1") == 3
    assert _outline_depth("2.3.1") == 4


def test_the_numbering_builds_the_path():
    codes = _codes(["I. Activos", "1. Inversión directa",
                    "1.1. Participaciones de capital"])
    assert "activos.inversion_directa.participaciones_de_capital" in codes


def test_a_sibling_replaces_its_peer_not_nests_under_it():
    """1.2 es hermano de 1.1, no su hijo."""
    codes = _codes(["I. Activos", "1. Inversión directa",
                    "1.1. Participaciones de capital", "1.2 Instrumentos de deuda"])
    assert "activos.inversion_directa.instrumentos_de_deuda" in codes
    assert not any("participaciones_de_capital.instrumentos" in c for c in codes)


def test_the_same_label_under_two_parents_stays_distinct():
    """El caso que motivó la regla: 'Banco Central' cuelga de dos ramas distintas y antes
    se desempataba por número de fila."""
    codes = _codes(["I. Activos", "2. Inversión de cartera",
                    "2.1 Participaciones de capital", "Banco Central",
                    "2.2 Títulos de deuda", "Banco Central"])
    assert "activos.inversion_de_cartera.participaciones_de_capital.banco_central" in codes
    assert "activos.inversion_de_cartera.titulos_de_deuda.banco_central" in codes
    assert not any(c.endswith(tuple(f"_r{i}" for i in range(20))) for c in codes)


def test_the_number_itself_is_not_part_of_the_name():
    codes = _codes(["I. Activos", "1. Inversión directa"])
    assert "activos.inversion_directa" in codes
    assert not any(c[0].isdigit() or "_1_" in c for c in codes)
