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

**La recaída del 2026-08-27, y lo que enseña.** La primera versión de la regla listó solo el
subjuntivo y el futuro —«cruce», «supere», «presionarán»— y se comió el INFINITIVO, que es
como el español dice una hipótesis la mayor parte de las veces. La frase que mató la primera
Revisión Anual pedida desde el selector nuevo fue: «la cobertura **puede cruzar** por debajo
del 100 %». Mismo verbo, otra forma, y el guard no la reconoció.

Por eso los casos de abajo están organizados por FORMA y no por verbo: el eje donde se abrió
el hueco es el que hay que ver de un vistazo. Y por eso el disparador es el VERBO y nunca el
modal — eximir por «puede» dejaría pasar «el indicador puede leerse como 1,40 %», que sí es
una cita.
"""
import pytest

from shared.narrative.numeric_guard import deterministic_uncited_figures

_CTX = {"entity_name": "Entidad", "period": "2025-12-31",
        "cobertura_provisiones": 108.36, "morosidad": 1.96}


#: Capturas LITERALES del registro de marcas de producción. No están redactadas a mano: son
#: el texto que el modelo escribió y que el guard marcó. Una frase inventada por mí habría
#: pasado contra una regla rota — de hecho la que faltaba la escribió el modelo, no yo.
FRASES_REALES_DE_PRODUCCION = [
    # 2026-08-26 — futuro y subjuntivo. Éstas la primera versión sí las cubría.
    "convergirá hacia niveles que presionarán la cobertura de provisiones por debajo de 100%",
    "la relación de eficiencia operativa —si supera 95%, la entidad operará en pérdida",
    "que la morosidad cruce 2.5% con migración sostenida por encima de 2%",
    # 2026-08-27 — INFINITIVO tras modal. Ésta mató una Revisión Anual entera.
    "sugiere que la presión no está agotada— la cobertura puede cruzar por debajo del 100% "
    "sin que se requiera un deterioro adicional de gran magnitud",
]


@pytest.mark.parametrize("frase", FRASES_REALES_DE_PRODUCCION)
def test_las_frases_REALES_que_mataron_informes(frase):
    """Cada una costó un informe. Ninguna vuelve a costarlo sin que este archivo se ponga
    rojo."""
    assert deterministic_uncited_figures(_CTX, frase) == []


@pytest.mark.parametrize("frase", [
    # SUBJUNTIVO
    "que la cobertura de provisiones caiga por debajo de 100%",
    "en caso de que el índice descienda a 12%",
    # FUTURO
    "la solvencia bajará hacia 14% si el crédito no se recupera",
    # CONDICIONAL
    "la morosidad cruzaría 3% en un escenario de deterioro",
    "el margen se ubicaría cerca de 45% con esa presión",
    # INFINITIVO — el eje que faltaba, con y sin modal
    "la cobertura puede cruzar por debajo del 100%",
    "el indicador podría superar 95% antes del cierre",
    "sin capital fresco, la solvencia tendería a rondar 11%",
    "al acercarse a 100%, la entidad comprime su margen para atender retiros",
])
def test_un_umbral_prospectivo_NO_es_una_cita(frase):
    assert deterministic_uncited_figures(_CTX, frase) == []


def test_el_MODAL_por_si_solo_NO_exime(frase=None):
    """El disparador es el verbo de cruce, no «puede».

    Si bastara el modal, «el indicador puede leerse como 4,44 %» quedaría exento — y eso es
    una CITA, no un umbral. Es el borde exacto entre las dos familias, y sin este caso la
    tentación de eximir por modal (que es más fácil de escribir) no encuentra resistencia.
    """
    assert deterministic_uncited_figures(_CTX, "El indicador puede leerse como 4.44%") != []


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
