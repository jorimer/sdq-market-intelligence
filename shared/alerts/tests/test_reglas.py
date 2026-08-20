"""Las reglas puras — y la regla que gobierna a todas: `None` de entrada, `None` de salida.

El barrido genérico de :func:`test_ninguna_entrada_none_dispara` es el que importa. La
versión escrita a mano de este test (una llamada por regla) protege lo que su autor se acordó
de probar; la que recorre la firma protege también los parámetros que se agreguen después,
que son justo los que nadie vuelve a mirar.
"""
import inspect
import typing

import pytest

from shared.alerts import reglas
from shared.alerts.reglas import AlertEvent, rule_banda, rule_brecha, rule_umbral

# Un juego de argumentos VÁLIDO por regla: el que sí dispara. Cada test parte de acá y
# rompe una cosa a la vez, para que el motivo del `None` no sea ambiguo.
VALIDOS = {
    rule_umbral: dict(
        sector_key="banking", subject="b1", sujeto_label="Banco A", periodo="2026-Q2",
        metrica="cobertura", metrica_label="Cobertura de provisiones", valor=91.0,
        umbral=100.0, direccion="por_debajo", severidad="alta", basis="crisis RD 2003"),
    rule_banda: dict(
        sector_key="banking", subject="b1", sujeto_label="Banco A", periodo="2026-Q2",
        banda_actual="baja", banda_previa="alta", orden_bandas=("alta", "media", "baja"),
        basis="presión del conjunto"),
    rule_brecha: dict(
        sector_key="banking", subject="b1", sujeto_label="Banco A", periodo="2026-Q2",
        dimension="solvencia", dimension_label="Solvencia", tenia_dato=True,
        tiene_dato=False, basis="panel de precursores"),
}


# Parámetros opcionales que la regla NO evalúa: los transporta al evento y el gate los
# juzga después. Excluirlos es una excepción DECLARADA, no un agujero:
#
# - ``frescura`` es el caso importante. Con ``frescura=None`` la regla **tiene que disparar
#   igual**, para que el evento exista y el gate lo vete DEJANDO CONSTANCIA. Si la regla
#   callara, el veto sería silencioso — y un veto callado se lee como que el eje no tenía
#   nada que avisar, que es la lectura opuesta a la verdadera. Lo cubre
#   :func:`test_frescura_indeterminada_NO_calla_a_la_regla`.
# - ``procedencia`` y ``clave_valor`` son rótulos del productor; su ausencia degrada a un
#   default honesto, no invalida la señal.
PASO: frozenset = frozenset({"frescura", "procedencia", "clave_valor"})


def _opcionales(fn):
    """Parámetros de *fn* que aceptan ``None`` y que la regla EVALÚA para decidir.

    Se RESUELVEN con ``get_type_hints``, no se leen de ``signature``: ``reglas.py`` usa
    ``from __future__ import annotations``, así que ahí las anotaciones son cadenas y ningún
    ``get_origin`` las reconoce. La primera versión de este helper devolvía la lista vacía y
    pytest reportaba «1 skipped» en vez de fallar — un barrido que no barre nada no avisa
    que no está barriendo. Por eso además está :func:`test_el_barrido_no_esta_vacio`.
    """
    out = []
    hints = typing.get_type_hints(fn)
    for nombre in inspect.signature(fn).parameters:
        anot = hints.get(nombre)
        if anot is None:
            continue
        if nombre in PASO:
            continue
        if typing.get_origin(anot) is typing.Union and type(None) in typing.get_args(anot):
            out.append(nombre)
    return out


def test_hay_reglas_que_revisar():
    """Si el catálogo de este test se vacía, todo lo de abajo pasaría sin proteger nada."""
    assert len(VALIDOS) == len(reglas.implementados()), (
        "hay reglas implementadas que este test no ejercita")


@pytest.mark.parametrize("fn", list(VALIDOS), ids=lambda f: f.__name__)
def test_el_barrido_no_esta_vacio(fn):
    """Sin esto, un helper que devuelve `[]` deja el barrido en «skipped» y el suite en
    verde. Es la misma clase de defecto que un binding a una serie inexistente: no falla,
    desaparece."""
    assert _opcionales(fn), f"{fn.__name__}: el barrido de None no encontró ningún parámetro"


@pytest.mark.parametrize("fn", list(VALIDOS), ids=lambda f: f.__name__)
def test_el_caso_valido_si_dispara(fn):
    """La base de todo lo demás: si el caso válido no disparara, los tests de `None`
    pasarían por la razón equivocada."""
    assert isinstance(fn(**VALIDOS[fn]), AlertEvent)


@pytest.mark.parametrize(
    "fn,param",
    [(fn, p) for fn in VALIDOS for p in _opcionales(fn)],
    ids=lambda x: x if isinstance(x, str) else x.__name__)
def test_ninguna_entrada_none_dispara(fn, param):
    """Un dato ausente no dispara ni deja de disparar: no se evalúa.

    Es donde más barato se viola la doctrina de la brecha: ``if valor > umbral`` con
    ``valor=None`` levanta y se nota, pero ``if (valor or 0) > umbral`` no levanta —
    publica un umbral que nadie cruzó.
    """
    kwargs = dict(VALIDOS[fn])
    kwargs[param] = None
    assert fn(**kwargs) is None, f"{fn.__name__} disparó con {param}=None"


# ── Lo que cada regla computa ────────────────────────────────────────────────

def test_umbral_computa_la_direccion_y_el_texto_la_copia():
    """La glosa no puede contradecir al número: la dirección sale de comparar las cifras y
    el texto la toma de ahí. Este repo ya publicó dos veces una glosa que sobrevivió a
    corregir el número."""
    e = rule_umbral(**VALIDOS[rule_umbral])
    assert e.relaciones["direccion"] == "por_debajo"
    assert "por debajo" in e.cuerpo
    assert e.relaciones["distancia"] == 9.0


def test_umbral_no_dispara_del_lado_sano():
    e = rule_umbral(**{**VALIDOS[rule_umbral], "valor": 120.0})
    assert e is None


def test_umbral_con_direccion_desconocida_calla():
    """Antes que inventar de qué lado del umbral está algo, callar."""
    assert rule_umbral(**{**VALIDOS[rule_umbral], "direccion": "de_costado"}) is None


def test_umbral_usa_notacion_de_la_casa():
    """Coma decimal. Una alerta con punto decimal se lee como de otro sistema que el que
    firma los informes."""
    e = rule_umbral(**VALIDOS[rule_umbral])
    assert "91,00%" in e.cuerpo and "100,00%" in e.cuerpo


def test_banda_lee_la_direccion_del_ORDEN_no_de_los_rotulos():
    """La polaridad de banca está invertida (100 = ningún precursor activo, banda «alta» es
    la MEJOR). Si la dirección saliera de comparar los rótulos, un deterioro se publicaría
    como mejora."""
    e = rule_banda(**VALIDOS[rule_banda])           # alta → baja, con ese orden, empeora
    assert e.relaciones["direccion"] == "deterioro"
    assert e.relaciones["saltos"] == 2
    assert e.severidad == "alta"

    inverso = rule_banda(**{**VALIDOS[rule_banda],
                            "banda_actual": "alta", "banda_previa": "baja"})
    assert inverso.relaciones["direccion"] == "mejora"
    assert inverso.severidad == "baja"


def test_banda_sin_cambio_no_dispara():
    assert rule_banda(**{**VALIDOS[rule_banda], "banda_actual": "alta"}) is None


def test_banda_fuera_del_orden_declarado_calla():
    """Una banda que no está en el orden no se puede juzgar. Callar es correcto: inventar
    la dirección es cómo se publica lo contrario de lo que pasó."""
    assert rule_banda(**{**VALIDOS[rule_banda], "banda_actual": "inventada"}) is None


def test_brecha_exige_la_TRANSICION_no_la_foto():
    """Sin dato y sin dato antes no es noticia: es el estado. Lo que se declara es el
    cambio."""
    assert rule_brecha(**{**VALIDOS[rule_brecha], "tenia_dato": False}) is None
    perdio = rule_brecha(**VALIDOS[rule_brecha])
    assert perdio.relaciones["direccion"] == "pierde"
    recupero = rule_brecha(**{**VALIDOS[rule_brecha],
                              "tenia_dato": False, "tiene_dato": True})
    assert recupero.relaciones["direccion"] == "recupera"


def test_la_clave_de_dedup_ignora_el_periodo():
    """Dos barridos sobre el mismo problema son el mismo aviso. Con el período adentro, cada
    trimestre re-avisaría lo mismo aunque nada hubiera cambiado — que es el ruido que mata
    el producto."""
    a = rule_umbral(**VALIDOS[rule_umbral])
    b = rule_umbral(**{**VALIDOS[rule_umbral], "periodo": "2026-Q3"})
    assert a.clave_dedup == b.clave_dedup


def test_el_evento_es_inmutable():
    """Lo que el gate juzga tiene que ser lo que se entrega: si un paso intermedio pudiera
    reescribir el texto después del veredicto, el gate no garantizaría nada."""
    e = rule_umbral(**VALIDOS[rule_umbral])
    with pytest.raises(Exception):
        e.cuerpo = "otra cosa"  # type: ignore[misc]


def test_frescura_indeterminada_NO_calla_a_la_regla():
    """La regla dispara y el GATE veta — no al revés.

    Es la diferencia entre «hay tres señales retenidas porque el dato no está vigente» y el
    silencio. Si la regla se callara con ``frescura=None``, el evento no existiría, no se
    persistiría, y nadie podría saber que el gate frenó algo.
    """
    from shared.alerts.gate import juzgar

    e = rule_umbral(**{**VALIDOS[rule_umbral], "frescura": None})
    assert e is not None                       # la regla NO calla
    v = juzgar(e)
    assert v.publica is False                  # el gate SÍ veta
    assert v.motivo == "frescura_indeterminada"
