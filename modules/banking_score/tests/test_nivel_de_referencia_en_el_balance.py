"""El contexto anual no servía el NIVEL DE REFERENCIA de cada indicador, y eso mataba informes.

**El caso, dos veces el mismo día.** El 2026-08-27 dos Revisiones Anuales murieron vetadas
por la misma cifra: `100%`. Las frases, capturadas literales del registro de marcas:

    «la cobertura PUEDE CRUZAR por debajo del 100 % sin que se requiera…»
    «La entidad aún mantiene provisiones POR ENCIMA DEL 100 % de su cartera vencida…»

Ese 100 % no es una alucinación: es `ref = 100.0` de `calc_cobertura_provisiones` — el nivel
en que las provisiones cubren exactamente la cartera vencida. Está en el motor desde siempre.
El modelo lo escribe porque **un ratio no se puede leer sin su referencia**, y el contexto no
se lo servía.

**Por qué mi primer arreglo fue el equivocado.** Traté el síntoma como un problema de LENGUAJE
—ampliar el detector para que reconociera «puede cruzar»— cuando era un HUECO EN EL DATO. La
doctrina del repo ya lo decía: «si no tenés la cifra que el modelo va a necesitar, pasásela
igual con su nombre real: dejar el hueco es lo que lo llena mal». Con la referencia servida,
la cifra tiene respaldo y el guard no tiene nada que vetar — sin ampliar ninguna exención.

**Y por qué el trimestral nunca falló así:** su Deep Dive sirve la tabla de sensibilidad, que
trae los umbrales. El contexto anual era más pobre que el del corte. Es el patrón conocido
—«un guard existe en un motor y falta en el otro»— del lado del DATO en vez del guard.
"""
from __future__ import annotations

import pytest

from modules.banking_score.scoring.sensitivity import _CURVES, nivel_de_referencia
from shared.narrative.numeric_guard import deterministic_uncited_figures

#: Frases REALES del registro de marcas. No redactadas por mí: las escribió el modelo.
FRASES_QUE_MATARON_INFORMES = [
    "la cobertura puede cruzar por debajo del 100% sin que se requiera un deterioro adicional",
    "La entidad aún mantiene provisiones por encima del 100% de su cartera vencida",
]


def _contexto_con_referencia(referencia=100.0):
    return {"revision_anual": {"entidad": "Entidad", "balance": [{
        "indicador": "cobertura_provisiones", "unidad": "%",
        "apertura": 136.21, "cierre": 96.75, "cambio": -39.46,
        "nivel_de_referencia": referencia,
        "contra_la_referencia": "por debajo"}]}}


def test_la_referencia_de_cobertura_es_100_y_sale_de_la_CURVA(): 
    """100 % no se escribe a mano en ningún lado nuevo: se computa invirtiendo la curva del
    motor, donde `ref` está fijada en el score 50 por construcción. Escribirla a mano sería
    la tercera copia del mismo número y la primera en desincronizarse."""
    assert nivel_de_referencia("cobertura_provisiones", 96.75) == 100.0


@pytest.mark.parametrize("frase", FRASES_QUE_MATARON_INFORMES)
def test_con_la_referencia_servida_el_guard_no_tiene_nada_que_vetar(frase):
    assert deterministic_uncited_figures(_contexto_con_referencia(), frase) == []


def test_SIN_la_referencia_el_guard_vetaba():
    """La prueba de que el hueco era la causa. Sin este caso, el de arriba pasaría igual si
    el guard hubiese dejado de mirar, y no sabría distinguirlo.

    Se usa **la segunda** frase, no las dos: la primera («puede cruzar») está cubierta
    ADEMÁS por la regla del umbral prospectivo, así que quitarle la referencia no la hace
    fallar. Son dos defensas independientes sobre la misma cifra y conviene no confundirlas
    — parametrizar las dos acá haría fallar el test por el motivo equivocado.
    """
    frase = "La entidad aún mantiene provisiones por encima del 100% de su cartera vencida"
    ctx = _contexto_con_referencia()
    del ctx["revision_anual"]["balance"][0]["nivel_de_referencia"]
    assert deterministic_uncited_figures(ctx, frase) != []


def test_la_frase_PROSPECTIVA_esta_cubierta_por_las_DOS_defensas():
    """Cinturón y tirantes, declarado: si mañana se afloja una, la otra sostiene — y este
    test dice cuál es cuál en vez de dejarlo a la arqueología."""
    prospectiva = ("la cobertura puede cruzar por debajo del 100% sin que se requiera un "
                   "deterioro adicional")
    sin_ref = _contexto_con_referencia()
    del sin_ref["revision_anual"]["balance"][0]["nivel_de_referencia"]
    assert deterministic_uncited_figures(sin_ref, prospectiva) == [], "la regla prospectiva"
    assert deterministic_uncited_figures(_contexto_con_referencia(), prospectiva) == []


def test_una_cifra_REALMENTE_inventada_se_sigue_marcando():
    """Servir la referencia no es aflojar el guard: es darle el dato que le faltaba."""
    assert deterministic_uncited_figures(
        _contexto_con_referencia(), "La cobertura se ubicó en 77.7% al cierre") != []


def test_TODOS_los_indicadores_con_curva_declaran_su_referencia():
    """Barrido: si mañana se agrega un indicador con curva y su referencia no sale, el
    informe que la necesite va a morir por lo mismo. Con su prueba negativa al lado."""
    assert len(_CURVES) >= 10, "el barrido no encontró curvas: no probó nada"
    sin_referencia = [k for k in _CURVES if nivel_de_referencia(k, 10.0) is None]
    assert sin_referencia == [], (
        f"Estos indicadores tienen curva pero no devuelven referencia: {sin_referencia}")


def test_el_balance_del_anio_SIRVE_la_referencia():
    """La ruta real: el nivel tiene que llegar a la fila del balance, no solo existir."""
    from modules.banking_score.reports.revision_anual import _balance

    cortes = ["2024-12-31", "2025-12-31"]
    indicadores = {"cobertura_provisiones": [
        {"period_end": "2024-12-31", "raw": 136.21},
        {"period_end": "2025-12-31", "raw": 96.75}]}
    fila = _balance(indicadores, cortes)[0]
    assert fila["nivel_de_referencia"] == 100.0
    assert fila["contra_la_referencia"] == "por debajo"
    assert "50 sobre 100" in (fila["nivel_de_referencia_significa"] or "")


def test_el_balance_sirve_tambien_el_SCORE_de_cada_indicador():
    """El mismo hueco, encontrado al buscar la clase en vez de la instancia.

    El score de cada indicador YA viajaba en la trayectoria y `_balance` lo descartaba,
    mientras el contexto del trimestral sí lo tiene. Un número que existe y no se sirve es
    un número que el modelo va a poner de memoria — y ahí es donde el guard lo mata.
    """
    from modules.banking_score.reports.revision_anual import _balance

    indicadores = {"cobertura_provisiones": [
        {"period_end": "2024-12-31", "raw": 136.21, "score": 82.0},
        {"period_end": "2025-12-31", "raw": 96.75, "score": 48.4}]}
    fila = _balance(indicadores, ["2024-12-31", "2025-12-31"])[0]
    assert fila["score_apertura"] == 82.0
    assert fila["score_cierre"] == 48.4
    assert fila["cambio_de_score"] == -33.6


def test_un_indicador_sin_score_NO_inventa_un_cero():
    """`None` es «no hay dato»; `0.0` sería «puntúa cero», que es otra cosa y peor."""
    from modules.banking_score.reports.revision_anual import _balance

    indicadores = {"cobertura_provisiones": [
        {"period_end": "2024-12-31", "raw": 136.21},
        {"period_end": "2025-12-31", "raw": 96.75}]}
    fila = _balance(indicadores, ["2024-12-31", "2025-12-31"])[0]
    assert fila["score_apertura"] is None and fila["cambio_de_score"] is None
