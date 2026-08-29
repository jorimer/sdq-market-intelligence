"""Un indicador DERIVADO no entra en la lista que agrega a sus propios componentes.

El caso. `composite_calidad` es la media de los siete indicadores de Calidad, y estaba
además dentro de `CALIDAD_INDICATORS`, la lista que la dimensión promedia. Medido sobre el
panel de producción, eso no movía el score ni una centésima —promediar la media de un
conjunto junto al conjunto da la misma media, para cualquier subconjunto disponible—, así
que durante meses fue inofensivo.

Lo que lo hacía peligroso era el futuro: Solidez ya pasó de promedio simple a promedio por
FAMILIA porque tres de sus cinco indicadores medían el mismo hecho. El día que Calidad
reciba un tratamiento parecido, un compuesto con peso propio hace que cada componente cuente
dos veces, y el defecto entra por una puerta que nadie está mirando. Se quita ahora, y esto
impide que vuelva.

La distinción es estructural, no una lista de nombres: un indicador con calculador propio en
`_INDICATOR_FUNCS` es MEDIDO; uno que se arma después del bucle a partir de otros es
DERIVADO. Solo los medidos votan.
"""

import pytest

from modules.banking_score.scoring import engine
from modules.banking_score.scoring.weights import (
    CALIDAD_INDICATORS,
    DIVERSIFICACION_INDICATORS,
    EFICIENCIA_INDICATORS,
    LIQUIDEZ_INDICATORS,
    SOLIDEZ_INDICATORS,
)

_DIMENSIONES = {
    "solidez": SOLIDEZ_INDICATORS,
    "calidad": CALIDAD_INDICATORS,
    "eficiencia": EFICIENCIA_INDICATORS,
    "liquidez": LIQUIDEZ_INDICATORS,
    "diversificacion": DIVERSIFICACION_INDICATORS,
}


def test_el_barrido_mira_las_cinco_dimensiones():
    """Una aserción de ausencia pasa sola: esto comprueba que hay dónde mirar."""
    assert len(_DIMENSIONES) == 5
    assert sum(len(v) for v in _DIMENSIONES.values()) >= 15


@pytest.mark.parametrize("dimension", sorted(_DIMENSIONES))
def test_solo_votan_los_indicadores_MEDIDOS(dimension):
    derivados = [k for k in _DIMENSIONES[dimension] if k not in engine._INDICATOR_FUNCS]
    assert not derivados, (
        f"{dimension} agrega {derivados}, que no tiene calculador propio: es un DERIVADO de "
        f"los otros miembros de esta misma lista. Hoy puede no mover el score —promediar la "
        f"media junto al conjunto da la misma media— pero en cuanto la dimensión pondere, "
        f"cada componente contará dos veces.")


def test_el_compuesto_de_calidad_sigue_calculandose_y_publicandose():
    """Sacarlo de la agregación NO es borrarlo: es el resumen que el informe muestra."""
    from modules.banking_score.scoring.indicator_detail import INDICATOR_META
    assert "composite_calidad" in INDICATOR_META
    ind = engine.calculate_all_indicators(engine.BankingDataInput(morosidad_pct=3.0))
    assert "composite_calidad" in ind, "el resumen dejó de calcularse"


def test_el_compuesto_es_la_media_de_LOS_QUE_LA_DIMENSION_AGREGA():
    """Sus componentes y los que la dimensión promedia son la MISMA lista, no dos copias."""
    assert list(engine._CALIDAD_COMPONENT_KEYS) == list(CALIDAD_INDICATORS)
