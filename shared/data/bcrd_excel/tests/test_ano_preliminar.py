"""El BCRD marca los años preliminares, y el eje de períodos tiene que reconocerlos igual.

**El defecto.** `_axis_year` —la detección del eje temporal— aceptaba la nota al pie con
barra («2008 3/») y no los marcadores que el BCRD usa de verdad para los años preliminares o
revisados: `2011*`, `2013**`, `2021 (p)`. Como esos años caían del eje, el rango de columnas
se cortaba en el último año «limpio» y las columnas siguientes —con dato— no se leían nunca.

Es la causa de los dos truncamientos que quedaban en el corpus canónico:

* `bpagos.xls` perdía **2011, 2012 y 2013** (marcados `2011*`, `2012**`, `2013**`).
* `lleg_total.xls` perdía **2026**, el año en curso (marcado `2026*`).

Y explica algo más grande: en `pib_origen_2018.xlsx` casi todos los años del encabezado están
marcados `(p)`, así que la heurística no encontró eje, devolvió confianza 0,0 y el trabajo
cayó en el modelo — que a su vez veía la vista previa cortada y truncaba el rango. Un solo
rótulo no reconocido encadenó los dos defectos.

Lo que NO puede pasar es aflojar de más: un año dentro de un subtítulo («Bases 1999 y 2010»)
o de un rango («1991-2013») sigue sin ser un eje de períodos.
"""
import pytest

from shared.data.bcrd_excel.inference import _axis_year


@pytest.mark.parametrize("celda,anio", [
    (2011, 2011), (2011.0, 2011), ("2011", 2011),
    ("2008 3/", 2008),          # nota al pie con barra: ya andaba
    ("2011*", 2011),            # preliminar
    ("2012**", 2012),           # revisado
    ("2013 **", 2013),
    ("2021 (p)", 2021),         # preliminar, la grafía del PIB por origen
    ("2026 (P)", 2026),
    ("2024(p)", 2024),
])
def test_un_ano_marcado_sigue_siendo_un_ano(celda, anio):
    assert _axis_year(celda) == anio


@pytest.mark.parametrize("celda", [
    "Bases 1999 y 2010",        # año dentro de un subtítulo
    "1991-2013",                # un rango no es un período
    "1991 - 2014",
    "Trim Acum 91-14",
    "Componente",
    None, "", "  ",
    "12345", "199",
])
def test_lo_que_no_es_un_eje_de_periodos_sigue_sin_serlo(celda):
    assert _axis_year(celda) is None
