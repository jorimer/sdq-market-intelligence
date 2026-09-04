"""La TPM se publica en porcentaje y se persistía como fracción: 0,0525 en vez de 5,25.

Excel guarda una celda con formato de porcentaje como la FRACCIÓN —0,0525 se muestra «5,25%»
pero el valor almacenado es 0,0525— y el extractor lee el valor crudo, así que el formato se
pierde. `Serie_TPM.xlsx` está entero así, y su encabezado dice «En % anual»: el archivo
declara una unidad y guarda otra.

Verificado por tres caminos independientes, porque multiplicar valores es más peligroso que
corregir una etiqueta:

* En 2026-07 la TPM se persistía como **0,0525** mientras la tasa pasiva promedio es
  **6,90%**. Una tasa de política de 0,05% con depósitos al 6,9% no existe: el arbitraje la
  cerraría el mismo día.
* La facilidad permanente de depósito —el piso del corredor— se persistía como **0,045**, en
  la misma escala. El corredor es coherente a ×100 y absurdo tal cual.
* El máximo de la serie es **0,5**, que a ×100 da 50%: el nivel real de la TPM dominicana
  tras la crisis de 2003-2004.

Y el freno que hace segura la corrección: si el BCRD algún día republica el archivo ya en
porcentaje, multiplicar otra vez daría 525%. Por eso la escala se aplica SOLO cuando los
valores están en el rango de una fracción, y se declara cuando no.
"""
import pytest

from shared.data.base_client import Record
from shared.data.bcrd_excel import canonical
from shared.data.lineage import Lineage
from modules.macro_monitor.service import _con_unidades_curadas


def _rec(series, valor):
    return Record(series=series, period="2026-07", value=valor, unit="%",
                  lineage=Lineage(source="BCRD", license="público"))


TPM = "bcrd.xls.serie_tpm.tasa_de_politica_monetaria"


def test_la_tpm_en_fraccion_se_lleva_a_porcentaje():
    salida = _con_unidades_curadas([_rec(TPM, 0.0525)])
    assert salida[0].value == pytest.approx(5.25)


def test_el_corredor_entero_se_corrige_no_solo_la_tpm():
    """La facilidad de depósito y la lombarda están en la misma escala: corregir una sola
    rompería el corredor, que es la relación que hace legible a las tres."""
    for hoja in ("facilidades_permanentes_deposito", "lombarda"):
        salida = _con_unidades_curadas([_rec(f"bcrd.xls.serie_tpm.{hoja}", 0.045)])
        assert salida[0].value == pytest.approx(4.5)


def test_si_la_fuente_ya_viene_en_porcentaje_NO_se_multiplica():
    """El día que el BCRD republique el archivo en porcentaje, volver a multiplicar daría
    525%. El freno es el rango: una fracción de tasa vive por debajo de 1."""
    salida = _con_unidades_curadas([_rec(TPM, 5.25)])
    assert salida[0].value == pytest.approx(5.25), (
        "multiplicó un valor que ya estaba en porcentaje")


def test_un_nulo_no_se_multiplica():
    assert _con_unidades_curadas([_rec(TPM, None)])[0].value is None


def test_no_toca_series_de_otros_archivos():
    """La inflación mensual por quintil vale ~0,45 y ESO SÍ es un porcentaje: 0,45% en un
    mes. Un umbral por magnitud a secas la habría multiplicado por cien."""
    otra = "bcrd.xls.ipc_quintiles_base_2019_2020.quintil_1_tasa_de_inflacion_inflacion"
    assert _con_unidades_curadas([_rec(otra, 0.45)])[0].value == pytest.approx(0.45)


def test_toda_escala_curada_declara_su_evidencia():
    for prefijo, (factor, tope, evidencia) in canonical.ESCALAS_CURADAS.items():
        assert factor != 1
        assert tope > 0
        assert len(evidencia) > 80, (
            f"la corrección de escala de {prefijo} no explica contra qué se verificó")
