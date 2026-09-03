"""El `excel_series_suffix` de una entrada canónica tiene que resolver a una serie REAL.

**El defecto que cierra.** La entrada `imae` declaraba
`excel_series_suffix="serie_original_variacion_porcentual_interanual"` y ninguna de las 12
series que el archivo produce termina así — la real se llama `variacion_porcentual_interanual`,
sin el prefijo. Era la única de 33 entradas con puente que no resolvía a nada, y **nadie se
enteraba**: `ingest_canonical` ingiere archivos COMPLETOS, así que el dato entraba igual y el
sufijo roto solo rompía la trazabilidad (qué serie del archivo es la que el registro dice
citar) y cualquier verificación que dependa del puente.

**Cuál es la correcta se COMPUTA, no se elige por parecido de nombre.** Cuatro candidatas
tienen «interanual» en el nombre; solo una coincide con la variación interanual del índice
original. Elegir por el rótulo es exactamente cómo se llegó al sufijo equivocado.

El fixture es `imae.xlsx` (base 2007, congelado) y no el vigente `imae_2018.xlsx`: lo que se
verifica es la ESTRUCTURA de columnas del cuadro del IMAE, idéntica en los dos —14 series con
los mismos nombres—, y no hace falta sumar un binario al repo para eso.
"""
from pathlib import Path

import pytest

from shared.data.bcrd_excel import canonical
from shared.data.bcrd_excel.extract import extract_records
from shared.data.bcrd_excel.inference import infer_spec
from shared.data.bcrd_excel.workbook import load_workbook

FIXTURES = Path(__file__).parent / "fixtures"


def _series_del_imae():
    """{sufijo: {período: valor}} de lo que el motor saca del cuadro del IMAE."""
    wb = load_workbook(FIXTURES / "imae.xlsx")
    recs = extract_records(wb, infer_spec(wb, "imae.xlsx"))
    out: dict = {}
    for r in recs:
        out.setdefault(r.series.split(".", 3)[3], {})[r.period] = r.value
    return out


@pytest.fixture(scope="module")
def imae():
    return _series_del_imae()


def _entrada(clave):
    e = canonical.by_key(clave)
    assert e is not None, f"el registro canónico no declara `{clave}`"
    return e


@pytest.mark.parametrize("clave", ["imae", "imae_indice"])
def test_el_puente_del_imae_resuelve_a_una_serie_real(imae, clave):
    e = _entrada(clave)
    assert e.excel_series_suffix, f"`{clave}` no declara puente"
    hallada = [s for s in imae if s.endswith(e.excel_series_suffix)]
    assert hallada, (
        f"`{clave}` declara el sufijo {e.excel_series_suffix!r} y NINGUNA de las "
        f"{len(imae)} series del archivo termina así. Disponibles: {sorted(imae)}"
    )
    assert len(hallada) == 1, f"`{clave}` resuelve a más de una serie: {hallada}"


def test_la_serie_que_declara_imae_ES_la_variacion_del_indice(imae):
    """La comprobación que habría evitado el sufijo equivocado: la serie que el registro
    señala como el IMAE tiene que COINCIDIR con la variación interanual de su índice."""
    indice = imae["serie_original_indice"]
    declarada = imae[_entrada("imae").excel_series_suffix]

    def yoy(p):
        y, m = p.split("-")
        a, b = indice.get(p), indice.get(f"{int(y) - 1}-{m}")
        return None if (a is None or not b) else (a / b - 1) * 100

    comparables = [p for p in indice if yoy(p) is not None and declarada.get(p) is not None]
    assert len(comparables) > 100, f"solo {len(comparables)} períodos comparables"
    error = max(abs(declarada[p] - yoy(p)) for p in comparables)
    assert error < 1e-6, f"la serie declarada NO es la variación del índice: error {error} pp"


def test_el_indice_del_imae_no_es_la_variacion(imae):
    """`imae` e `imae_indice` son DOS series, no una corregida: tienen que apuntar a
    columnas distintas. Si alguien las hiciera coincidir, el nowcast se quedaría sin nivel."""
    assert _entrada("imae").excel_series_suffix != _entrada("imae_indice").excel_series_suffix
    assert _entrada("imae").source_file == _entrada("imae_indice").source_file
