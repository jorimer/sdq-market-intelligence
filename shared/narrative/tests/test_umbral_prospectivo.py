"""Un UMBRAL de una frase prospectiva no es una cita — y el falso positivo rompía el producto.

Cuarta familia de falso positivo del guard, y la primera que no vetaba sino que **rompía**.
Las tres anteriores eran una FORMA de un número servido (redondeo, razón en porcentaje, peso
en un contenedor). Ésta no corresponde a ningún número del contexto y no debería: «si la
cobertura CAIGA por debajo de 100 %» es una condición futura, y el dato describe el pasado.

**El daño medido en producción** (Revisión Anual, 2026-08-26): el guard marcaba estos umbrales
en las dos secciones, disparaba el lazo de reparación en cada intento y la petición llegaba a
**16 llamadas al modelo para DOS secciones**. Cruzaba el límite del proxy y moría con un 502
sin cuerpo — el frontend, que lee `detail`, no tenía nada que mostrar salvo «No se pudo cargar
el producto». Ni siquiera era un veto explicado: era un producto que no cargaba.

Las frases de este archivo son las REALES, recuperadas del registro de marcas.
"""
import pytest

from shared.narrative.numeric_guard import deterministic_uncited_figures

_CTX = {"entity_name": "Entidad", "period": "2025-12-31",
        "cobertura_provisiones": 108.36, "morosidad": 1.96}


@pytest.mark.parametrize("frase", [
    "convergirá hacia niveles que presionarán la cobertura de provisiones por debajo de 100%",
    "la relación de eficiencia operativa —si supera 95%, la entidad operará en pérdida",
    "al acercarse a 100%, la entidad comprime su margen para atender retiros",
    "que la morosidad cruce 2.5% con migración sostenida por encima de 2%",
    "que la cobertura de provisiones caiga por debajo de 100%",
])
def test_un_umbral_prospectivo_NO_es_una_cita(frase):
    assert deterministic_uncited_figures(_CTX, frase) == []


@pytest.mark.parametrize("frase", [
    "la cobertura de provisiones se ubica en 142% al cierre",
    "la morosidad alcanzó 7.7% en el trimestre",
    "el ROA del año fue 3.9%",
    "el apalancamiento equivale al 512% del promedio del sistema",
])
def test_una_afirmacion_de_HECHO_se_sigue_marcando(frase):
    """Los dientes. Sin esto, la regla se satisface no marcando nunca — y el guard entero
    existe para atrapar exactamente estas frases."""
    assert deterministic_uncited_figures(_CTX, frase)


def test_la_marca_prospectiva_tiene_que_estar_CERCA():
    """Un «si» al principio del párrafo no exime a todo lo que venga después.

    Sin la ventana, una sola condicional al inicio apagaría el guard para el resto del texto,
    que es como un falso NEGATIVO entra por la puerta que abrió un falso positivo.
    """
    lejos = ("Si el entorno se deteriora, la entidad enfrentará presiones. " + "Además, "
             "la gestión ha mantenido una operación estable durante todo el ejercicio y el "
             "consejo ha ratificado su política de dividendos sin cambios relevantes. "
             "La cobertura de provisiones se ubica en 142% al cierre.")
    assert deterministic_uncited_figures(_CTX, lejos)
