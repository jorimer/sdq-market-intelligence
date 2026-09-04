"""Cuando el emisor rotula mal su propia unidad, la corrección se CURA y se demuestra.

`Remesas_6.xlsx` titula «MILLONES DE US$» y sus celdas traen 280.155.040 para enero de 2010.
Las dos cosas juntas dirían que en un mes entraron 280 billones de dólares. La cifra correcta
la publica el propio BCRD en su balanza de pagos MBP6: remesas 2010 = 3.683 millones de US$.
La suma de los doce meses de la planilla da **3.682.932.483**, o sea 3.683 millones — las
celdas están en US$ y el rótulo se equivoca por un factor de un millón.

Por qué esto es una excepción y no una puerta abierta: la unidad del emisor manda siempre
(`series_nature` se construyó sobre eso), y sobrescribirla exige una VERIFICACIÓN CONTRA
OTRA PUBLICACIÓN DEL MISMO EMISOR, escrita al lado de la corrección. No se corrige una
unidad porque el número «se ve raro».
"""
from shared.data.base_client import Record
from shared.data.lineage import Lineage
from shared.data.bcrd_excel import canonical
from modules.macro_monitor.service import _con_unidades_curadas


def _rec(series, unit):
    return Record(series=series, period="2010-01", value=1.0, unit=unit,
                  lineage=Lineage(source="BCRD", license="público"))


def test_la_unidad_curada_reemplaza_la_del_emisor():
    salida = _con_unidades_curadas([_rec("bcrd.xls.remesas_6.valor", "Millones de US$")])
    assert salida[0].unit == "US$"


def test_no_toca_lo_que_no_esta_curado():
    salida = _con_unidades_curadas([_rec("bcrd.xls.pib_2018.serie_original_indice", "Índice")])
    assert salida[0].unit == "Índice"


def test_toda_correccion_declara_su_evidencia():
    for prefijo, (unidad, evidencia) in canonical.UNIDADES_CURADAS.items():
        assert unidad, f"{prefijo} no declara unidad"
        assert len(evidencia) > 60, (
            f"la corrección de {prefijo} no explica contra qué se verificó: {evidencia!r}")
