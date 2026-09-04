"""Cuando un rótulo se repite en un cuadro, el PRIMERO tampoco queda identificado.

En la balanza de pagos, «Exportaciones» e «Importaciones» tienen cada una las mismas dos
sub-filas: «Nacionales» y «Zonas Francas». No hay numeración ni sangría que las ordene — la
jerarquía está solo en la aritmética (exportaciones = nacionales + zonas francas)—, así que
las cuatro cuelgan del mismo padre y colisionan de a dos.

El desempate marcaba solo a la SEGUNDA (`nacionales_r17`), que después el nombrado semántico
resuelve a `…importaciones.nacionales`. La primera se quedaba como
`…balanza_de_bienes.nacionales`: nacionales ¿de qué? De las exportaciones — pero el código no
lo dice, y al lado hay una serie que sí dice «importaciones», lo que invita a leer la otra
como el agregado. Es la misma corrección que ya se hizo en `year_blocks` y en `period_rows`:
se califica a TODOS los que comparten el rótulo, no solo a los que llegan después.
"""
from shared.data.bcrd_excel.extract import extract_records
from shared.data.bcrd_excel.spec import ExtractionSpec
from shared.data.bcrd_excel.workbook import Grid, Workbook


def _wb():
    filas = [
        ["Concepto", 2010.0, 2011.0],
        ["1. Cuenta Corriente", -4023.5, -4334.6],
        ["1.1 Balanza de Bienes", -8393.9, -8939.7],
        ["Exportaciones", 6816.0, 8361.9],
        ["Nacionales", 2621.6, 3594.8],
        ["Zonas Francas", 4194.4, 4767.1],
        ["Importaciones", 15209.9, 17301.6],
        ["Nacionales", 12600.9, 14362.9],
        ["Zonas Francas", 2609.0, 2938.7],
    ]
    return Workbook(path=None, grids=[Grid(name="BOP", rows=filas)])


def _spec():
    return ExtractionSpec(
        file="bpagos_6.xls", sheet="BOP", orientation="matrix",
        data_row_start=1, period_header_row=0, label_col=0,
        value_col_start=1, value_col_end=3, code_prefix="p",
    )


def _codigos():
    return sorted({r.series for r in extract_records(_wb(), _spec())})


def test_ninguna_de_las_dos_repetidas_se_queda_con_el_codigo_a_secas():
    codigos = _codigos()
    for hoja in ("nacionales", "zonas_francas"):
        crudo = [c for c in codigos if c.endswith(f".{hoja}")]
        assert not crudo, (
            f"«{hoja}» aparece dos veces en el cuadro y una se quedó sin calificar: {crudo}")


def test_las_cuatro_sub_filas_siguen_existiendo():
    codigos = _codigos()
    assert sum(1 for c in codigos if "nacionales" in c) == 2
    assert sum(1 for c in codigos if "zonas_francas" in c) == 2


def test_los_agregados_no_se_tocan():
    codigos = _codigos()
    assert any(c.endswith(".exportaciones") for c in codigos)
    assert any(c.endswith(".importaciones") for c in codigos)
