"""Toda clave que llega al dict `indicators` tiene rótulo en `INDICATOR_META`.

**El defecto que lo motiva.** `_rotulo_y_valor` cae al fallback `clave.replace("_"," ").title()`
cuando la clave no está en el registro, y no avisa: la fila sale con el identificador
capitalizado y **el valor sin unidad**. Su propio docstring dice que ese fallback ya fue «un
bug real detectado en producción» para los títulos de sección, se corrigió allá y quedó vivo
acá — en la tabla que el comité mira primero.

Reapareció el 2026-08-30 en la muestra curada del Deep Dive, que declaraba sus indicadores
como `eficiencia` y `liquidez`. Esos son nombres de SUB-COMPONENTE, no de indicador: viven en
otro diccionario del mismo payload. La muestra imprimía «Eficiencia 56.00» y «Liquidez 31.00»,
sin etiqueta real y sin el `%`. Nada falló. Es la pieza que se le manda a un comprador.

**Qué queda afuera si el barrido se escribe mal.** La tentación es cruzar `INDICATOR_META`
contra `_INDICATOR_FUNCS`, el dispatch del motor. No alcanza: `composite_calidad` NO está en
el dispatch —se compone DESPUÉS de los demás y se escribe directo en el dict— y sin embargo
llega al payload y se guarda en `indicator_details` de producción. Un test anclado al
dispatch daría verde dejando esa clave y cualquier otra escritura directa sin cubrir. Por eso
las claves se leen del CÓDIGO con `ast`, sumando las dos formas.

La dirección inversa NO se exige: `INDICATOR_META` puede declarar claves que el motor ya no
computa, porque los `indicator_details` guardados en cortes viejos las siguen conteniendo y
hay que poder dibujarlas. Un registro que se poda rompe los informes históricos.
"""

import ast
import pathlib

import pytest

from modules.banking_score.scoring.engine import _INDICATOR_FUNCS
from modules.banking_score.scoring.indicator_detail import INDICATOR_META

_ENGINE = pathlib.Path("modules/banking_score/scoring/engine.py")

#: Los nombres de las cinco dimensiones. Viven en `sub_components`, nunca en `indicators`, y
#: confundir los dos diccionarios es exactamente lo que pasó.
SUB_COMPONENTES = frozenset({"solidez", "calidad", "eficiencia", "liquidez",
                             "diversificacion"})


def _claves_escritas_directo() -> set:
    """Claves asignadas como `indicators["<k>"] = …` en el motor — la forma que el dispatch
    no declara."""
    out = set()
    for nodo in ast.walk(ast.parse(_ENGINE.read_text())):
        if (isinstance(nodo, ast.Assign) and len(nodo.targets) == 1
                and isinstance(nodo.targets[0], ast.Subscript)
                and isinstance(nodo.targets[0].value, ast.Name)
                and nodo.targets[0].value.id == "indicators"
                and isinstance(nodo.targets[0].slice, ast.Constant)
                and isinstance(nodo.targets[0].slice.value, str)):
            out.add(nodo.targets[0].slice.value)
    return out


def _todas_las_claves() -> set:
    return set(_INDICATOR_FUNCS) | _claves_escritas_directo()


def test_el_barrido_ve_las_DOS_formas_de_escribir_un_indicador():
    """Una aserción de ausencia pasa sola. Esto comprueba que el lector encuentra tanto el
    dispatch como la escritura directa — si dejara de encontrar la segunda, el test de abajo
    seguiría en verde protegiendo la mitad."""
    directas = _claves_escritas_directo()
    assert directas, "el lector `ast` no encontró ninguna escritura directa a `indicators`"
    assert "composite_calidad" in directas, (
        "la clave que se escribe fuera del dispatch dejó de detectarse: el barrido ya no "
        "cubre esa forma")
    assert len(_todas_las_claves()) > len(_INDICATOR_FUNCS), (
        "el dispatch por sí solo NO es el universo de claves")


@pytest.mark.parametrize("clave", sorted(_todas_las_claves()))
def test_cada_clave_tiene_etiqueta_y_unidad(clave):
    meta = INDICATOR_META.get(clave)
    assert meta is not None, (
        f"«{clave}» llega al dict `indicators` y no está en INDICATOR_META: la tabla del "
        f"informe la imprimiría como «{clave.replace('_', ' ').title()}» y el valor SIN "
        f"unidad, sin que nada falle")
    assert meta.get("label"), f"«{clave}» no declara `label`"
    # La unidad puede ser la cadena vacía —un índice adimensional como el HHI o el resumen
    # de calidad—, pero la CLAVE tiene que estar: su ausencia es «nadie lo pensó», y el
    # renderizador no distingue eso de «no lleva unidad».
    assert "unit" in meta, (
        f"«{clave}» no declara `unit`. Vacío es una respuesta válida; ausente no: el "
        f"renderizador no puede distinguir «adimensional» de «se olvidó»")


@pytest.mark.parametrize("nombre", sorted(SUB_COMPONENTES))
def test_un_nombre_de_DIMENSION_no_es_una_clave_de_indicador(nombre):
    """Las dos familias conviven en el mismo payload, en dos diccionarios distintos.
    Escribir una dimensión donde va un indicador es el error que produjo el defecto, y no
    lo detecta ningún tipo: los dos son `str`."""
    assert nombre not in _todas_las_claves(), (
        f"«{nombre}» es una DIMENSIÓN (va en `sub_components`) y aparece como clave de "
        f"indicador")
    assert nombre not in INDICATOR_META, (
        f"«{nombre}» tiene rótulo de indicador: eso vuelve INVISIBLE la confusión, porque "
        f"la fila saldría bien etiquetada y seguiría estando en el diccionario equivocado")


def test_la_muestra_curada_declara_indicadores_REALES():
    """La muestra es la única parte del payload que se escribe a mano, y la que se le manda
    a un comprador. Es donde el defecto apareció."""
    from modules.banking_score.products import SAMPLE_SCORING
    for clave in SAMPLE_SCORING["indicators"]:
        assert clave in INDICATOR_META, (
            f"la muestra declara «{clave}», que no es un indicador del motor: su tabla "
            f"saldría sin etiqueta y sin unidad")
    assert not (set(SAMPLE_SCORING["indicators"]) & SUB_COMPONENTES)


def test_el_registro_PUEDE_declarar_claves_que_el_motor_ya_no_computa():
    """La dirección inversa no se exige, y conviene decir por qué: los `indicator_details`
    de cortes viejos siguen conteniendo claves retiradas, y hay que poder dibujarlas. Podar
    el registro rompería los informes históricos en silencio."""
    huerfanas = set(INDICATOR_META) - _todas_las_claves()
    # No se afirma que haya ninguna; se afirma que si las hay, NO son un fallo.
    assert isinstance(huerfanas, set)
