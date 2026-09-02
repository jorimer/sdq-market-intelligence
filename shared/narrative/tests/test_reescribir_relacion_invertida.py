"""Cuando el modelo no copia la lectura correcta, la escribe el SISTEMA.

Hasta hoy había dos salidas y las dos eran malas: **vetar** —negar quince secciones
correctas por una frase, y encima esquivable reintentando— o **anotar** al pie, que
documenta el error en vez de arreglarlo.

El sistema TIENE la frase correcta: la computa y se la entrega al modelo con «escribí
exactamente esto» (`_clausula_a_copiar`). Si después de dos intentos no la copia,
escribirla es lo único que deja el documento bien.

El caso que motivó todo: la §7 de un Deep Dive entregado afirmó que la capitalización
contable «supera en 3.70 puntos porcentuales al promedio de su grupo» cuando estaba POR
DEBAJO —7.41% contra 11.11%—, contradiciendo a la §2 y a la §10 del mismo documento.
"""
import pytest

from shared.narrative.numeric_guard import (
    deterministic_direction_errors, reescribir_relaciones_invertidas,
)

#: El contexto tal como el motor lo sirve: la comparación computada CON su lectura redactada.
_CTX = {
    "comparaciones": [{
        "indicador": "patrimonio_activos",
        "valor": 7.41,
        "referencia": "el promedio de su grupo",
        "valor_referencia": 11.11,
        "brecha_pp": -3.70,
        "direccion": "por debajo",
        "lectura": ("La capitalización contable se sitúa 3.70 puntos porcentuales por debajo "
                    "del promedio de su grupo."),
    }],
}

_INVERTIDA = ("La capitalización contable supera en 3.70 puntos porcentuales al promedio de "
              "su grupo.")


def test_el_detector_marca_la_frase_invertida():
    """Sin esto, todo lo demás podría estar probando un texto que nadie marca."""
    assert deterministic_direction_errors(_CTX, _INVERTIDA)


def test_la_reescribe_con_la_lectura_SERVIDA():
    texto, reemplazos = reescribir_relaciones_invertidas(_CTX, _INVERTIDA)
    assert reemplazos, "no reescribió nada"
    assert texto == _CTX["comparaciones"][0]["lectura"]
    assert not deterministic_direction_errors(_CTX, texto), "quedó marcada igual"


def test_NO_toca_lo_que_no_esta_marcado():
    """El contrapeso: sin él, esto pasaría con una función que reescribe todo siempre."""
    sano = "La capitalización contable se sitúa 3.70 puntos porcentuales por debajo del promedio de su grupo."
    texto, reemplazos = reescribir_relaciones_invertidas(_CTX, sano)
    assert texto == sano and reemplazos == []


def test_conserva_las_ORACIONES_VECINAS():
    """Reescribir una frase no puede llevarse el párrafo. El caso real tenía la inversión en
    el medio de una sección de quince líneas."""
    parrafo = ("El activo total creció 8.2% interanual. " + _INVERTIDA +
               " La liquidez inmediata se mantiene en 24.1%.")
    texto, reemplazos = reescribir_relaciones_invertidas(_CTX, parrafo)
    assert reemplazos
    assert "El activo total creció 8.2% interanual." in texto
    assert "La liquidez inmediata se mantiene en 24.1%." in texto
    assert "supera en 3.70" not in texto


def test_encuentra_la_oracion_aunque_cruce_un_SALTO_DE_LINEA():
    """El detector trabaja sobre el texto aplanado y el informe conserva su formato. Buscar
    la cadena literal fallaría en cuanto la oración se envuelva — que es lo normal en un
    párrafo, y justo donde el caso real se escondía."""
    envuelto = _INVERTIDA.replace("puntos porcentuales", "puntos\nporcentuales")
    texto, reemplazos = reescribir_relaciones_invertidas(_CTX, envuelto)
    assert reemplazos and "supera" not in texto


def test_SIN_lectura_servida_no_inventa_nada():
    """Si el contexto no trae la frase redactada, la oración queda como está y el hallazgo
    sigue vivo. Escribir una corrección que el sistema no computó sería inventar."""
    ctx = {"comparaciones": [{**_CTX["comparaciones"][0], "lectura": None}]}
    texto, reemplazos = reescribir_relaciones_invertidas(ctx, _INVERTIDA)
    assert texto == _INVERTIDA and reemplazos == []
    assert deterministic_direction_errors(ctx, texto), "el hallazgo tiene que seguir vivo"


def test_se_REVIERTE_si_la_sustitucion_no_arregla():
    """La sustitución es una promesa verificable, no un acto de fe: si el detector sigue
    marcando lo mismo, el reemplazo no sirvió y se deshace. Acá la 'lectura' está ella misma
    invertida — el peor insumo posible."""
    ctx = {"comparaciones": [{**_CTX["comparaciones"][0],
                              "lectura": _INVERTIDA}]}
    texto, reemplazos = reescribir_relaciones_invertidas(ctx, _INVERTIDA)
    assert reemplazos == [], "aplicó una sustitución que no resuelve el hallazgo"
    assert texto == _INVERTIDA


def test_un_contexto_roto_no_rompe_la_generacion():
    """Best-effort, como todos sus hermanos del guard."""
    for basura in ({}, {"comparaciones": None}, {"comparaciones": [42]}):
        texto, reemplazos = reescribir_relaciones_invertidas(basura, _INVERTIDA)
        assert texto == _INVERTIDA and reemplazos == []


def test_EL_MOTOR_lo_llama_de_verdad():
    """Un test del reescritor NO es un test de que alguien lo use.

    Es el modo de falla que este repo pagó cinco veces: el guard probado en el motor y la
    ruta sin él. Acá la variante es más sutil —la función existe, pasa sus ocho tests, y el
    motor podría no llamarla nunca—, así que se lee el fuente del punto donde el hallazgo
    sobrevive a los reintentos.
    """
    import inspect

    from shared.narrative import claude_engine

    fuente = inspect.getsource(claude_engine)
    i_llamada = fuente.find("reescribir_relaciones_invertidas(\n")
    if i_llamada < 0:
        i_llamada = fuente.find("reescribir_relaciones_invertidas(")
    i_registro = fuente.find("from shared.narrative.relaciones_pendientes import registrar")
    assert i_llamada > 0, "el motor no llama al reescritor"
    assert i_registro > 0, "el motor dejó de registrar lo que no pudo reparar"
    assert i_llamada < i_registro, (
        "se registra ANTES de intentar reescribir: el hallazgo se depositaría aunque el "
        "sistema pudiera arreglarlo")


def test_NADIE_veta_ya_por_una_relacion_invertida():
    """Las DOS superficies tienen que estar de acuerdo. El veto vivía en el ensamblador y en
    la ruta de reportes; sacarlo de una sola dejaría al mismo informe entregándose por un
    camino y negándose por el otro — según por dónde se pida."""
    import inspect

    from modules.banking_score.api import router_reports
    from shared.products import assembler

    for mod in (assembler, router_reports):
        fuente = inspect.getsource(mod)
        assert "raise NarrativeRelacionInvertidaError" not in fuente, (
            f"{mod.__name__} sigue vetando por relación invertida")
        assert "relaciones_pendientes" in fuente, (
            f"{mod.__name__} dejó de registrarlas: se entregarían en silencio")
