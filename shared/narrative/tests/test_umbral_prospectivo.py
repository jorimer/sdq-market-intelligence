"""El UMBRAL de una frase prospectiva no es una cita — pero tampoco puede ser inventado.

Cuarta familia de falso positivo del guard, y la primera que no vetaba sino que **rompía**.
Las tres anteriores eran una FORMA de un número servido (redondeo, razón en porcentaje, peso
en un contenedor). Ésta es una condición futura: «si la cobertura CAIGA por debajo de 100 %».

**El daño del 2026-08-26** (Revisión Anual): el guard marcaba estos umbrales, disparaba el lazo
de reparación en cada intento y la petición llegaba a 16 llamadas al modelo para DOS secciones,
hasta morir con un 502 sin cuerpo. La cura fue EXIMIR toda cifra de una frase prospectiva.

**El giro del 2026-09-15 (Banco Múltiple Santa Cruz).** La exención dejaba pasar CUALQUIER
cifra condicional, servida o no. El Deep Dive 2025 escribió «si la cobertura desciende de
120 %, la señal dejaría de ser de alerta temprana y pasaría a requerir ajuste»; el 120 no
existía en el código ni en el contexto, y el mismo informe citaba páginas antes el 100 % de
referencia. Un alto funcionario del banco preguntó de dónde salía, con razón. La exención
cerraba un falso positivo abriendo un falso negativo del peor tipo: un juicio de valor con
número propio, en la frase que el comité lee como recomendación.

**La regla hoy:** el umbral de una condición futura pasa si está SERVIDO (en cualquiera de sus
formas) y, si no, se MARCA con un aviso propio —usar el nivel servido o decir la condición sin
número—. Volver a marcar es viable por lo que no existía el 2026-08-26: el contexto sirve
`nivel_de_referencia` (el 100 % de la cobertura), la reparación tiene tope de dos reintentos y
presupuesto de tiempo, y la regla nace en el prompt (`UMBRAL_DISCIPLINE`).

Los casos están organizados por FORMA verbal, no por verbo: la recaída del 2026-08-27 fue un
infinitivo («puede cruzar») que la primera versión no reconocía, y reconocer la forma sigue
importando — ahora decide QUÉ aviso recibe el modelo.
"""
import pytest

from shared.narrative.numeric_guard import deterministic_uncited_figures

_CTX = {"entity_name": "Entidad", "period": "2025-12-31",
        "cobertura_provisiones": 108.36, "morosidad": 1.96,
        # El nivel en que la cobertura puntúa 50: lo sirve `revision_anual._balance`.
        "nivel_de_referencia": 100.0}

#: Los umbrales de los casos por forma, SERVIDOS. Con ellos cada frase debe pasar; sin ellos,
#: marcarse con el aviso de umbral.
_UMBRALES_SERVIDOS = {"umbrales_declarados": {"a": 100.0, "b": 13.0, "c": 14.0, "d": 3.0,
                                              "e": 45.0, "f": 95.0, "g": 11.0}}


def _es_aviso_de_umbral(marca: str) -> bool:
    return "umbral" in marca


#: Capturas LITERALES del registro de marcas de producción, las que mataron informes. Las que
#: condicionan sobre el 100 % tienen hoy su nivel servido y deben pasar sin reintento.
FRASES_REALES_CON_UMBRAL_SERVIDO = [
    "convergirá hacia niveles que presionarán la cobertura de provisiones por debajo de 100%",
    "sugiere que la presión no está agotada— la cobertura puede cruzar por debajo del 100% "
    "sin que se requiera un deterioro adicional de gran magnitud",
]

#: Y las que condicionan sobre un número que nadie sirvió. Eran exentas; son la misma familia
#: que el 120 % de Santa Cruz.
FRASES_REALES_CON_UMBRAL_INVENTADO = [
    # LITERAL del Deep Dive de Banco Múltiple Santa Cruz 2025, §Implicaciones.
    "La señal de vigilancia prioritaria para el próximo corte es la cobertura de provisiones: "
    "si desciende de 120%, la señal dejaría de ser de alerta temprana y pasaría a requerir "
    "ajuste en las condiciones de la exposición.",
    "la relación de eficiencia operativa —si supera 95%, la entidad operará en pérdida",
    "que la morosidad cruce 2.5% con migración sostenida",
]


@pytest.mark.parametrize("frase", FRASES_REALES_CON_UMBRAL_SERVIDO)
def test_las_frases_REALES_con_su_umbral_servido_pasan(frase):
    """Cada una costó un informe. Con el nivel servido, ninguna vuelve a costarlo."""
    assert deterministic_uncited_figures(_CTX, frase) == []


@pytest.mark.parametrize("frase", FRASES_REALES_CON_UMBRAL_INVENTADO)
def test_el_umbral_INVENTADO_se_marca_con_su_aviso(frase):
    marcas = deterministic_uncited_figures(_CTX, frase)
    assert marcas, "un umbral que el contexto no sirve no puede publicarse"
    assert all(_es_aviso_de_umbral(m) for m in marcas), marcas


FORMAS_PROSPECTIVAS = [
    # SUBJUNTIVO
    "que la cobertura de provisiones caiga por debajo de 100%",
    # 13 y no 12: el contexto trae el período «2025-12-31» y el guard toma su mes como valor.
    "en caso de que el índice descienda a 13%",
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
]


@pytest.mark.parametrize("frase", FORMAS_PROSPECTIVAS)
def test_cada_FORMA_con_su_umbral_servido_pasa(frase):
    ctx = {"entity_name": "Entidad", "period": "2025-12-31", **_UMBRALES_SERVIDOS}
    assert deterministic_uncited_figures(ctx, frase) == []


@pytest.mark.parametrize("frase", FORMAS_PROSPECTIVAS)
def test_cada_FORMA_sin_su_umbral_se_marca_como_umbral(frase):
    """La forma se sigue reconociendo: decide que el aviso sea el de UMBRAL y no el de cita.

    Para los casos sobre 100 %, el contexto de esta prueba NO sirve el nivel — es el mismo
    texto que arriba pasa, y lo único que cambia es si el número está servido."""
    ctx = {"entity_name": "Entidad", "period": "2025-12-31", "morosidad": 1.96}
    marcas = deterministic_uncited_figures(ctx, frase)
    assert marcas, "la fixture tiene que ejercitar la marca"
    assert all(_es_aviso_de_umbral(m) for m in marcas), marcas


def test_el_MODAL_por_si_solo_NO_hace_de_la_cita_un_umbral():
    """El disparador es el verbo de cruce, no «puede»: «puede leerse como 4,44 %» es una CITA
    y su aviso es el de cita."""
    marcas = deterministic_uncited_figures(_CTX, "El indicador puede leerse como 4.44%")
    assert marcas and not any(_es_aviso_de_umbral(m) for m in marcas)


@pytest.mark.parametrize("frase", [
    "la cobertura de provisiones se ubica en 142% al cierre",
    "la morosidad alcanzó 7.7% en el trimestre",
    "el ROA del año fue 3.9%",
    "el apalancamiento equivale al 512% del promedio del sistema",
])
def test_una_afirmacion_de_HECHO_se_marca_como_cita(frase):
    marcas = deterministic_uncited_figures(_CTX, frase)
    assert marcas and not any(_es_aviso_de_umbral(m) for m in marcas)


def test_la_regla_nace_en_el_prompt_de_AMBAS_rutas():
    """El guard es la red; sin la regla en el prompt, cada umbral de memoria cuesta dos
    regeneraciones y, si el modelo insiste, el informe."""
    from shared.narrative.cerebro import UMBRAL_DISCIPLINE, build_system
    from shared.narrative.claude_engine import _legacy_system

    assert "APETITO DE RIESGO" in UMBRAL_DISCIPLINE
    assert UMBRAL_DISCIPLINE in build_system("banking", "comite_credito", "deep")
    assert UMBRAL_DISCIPLINE in _legacy_system()


def test_la_marca_prospectiva_tiene_que_estar_CERCA():
    """Un «si» al principio del párrafo no convierte en umbral a todo lo que venga después."""
    lejos = ("Si el entorno se deteriora, la entidad enfrentará presiones. " + "Además, "
             "la gestión ha mantenido una operación estable durante todo el ejercicio y el "
             "consejo ha ratificado su política de dividendos sin cambios relevantes. "
             "La cobertura de provisiones se ubica en 142% al cierre.")
    marcas = deterministic_uncited_figures(_CTX, lejos)
    assert marcas and not any(_es_aviso_de_umbral(m) for m in marcas)
