"""Paridad de DECLARACIONES entre el Deep Dive trimestral y la Revisión Anual.

**Por qué existe este archivo.** El producto anual lo construí sin comparar su contexto ni su
documento contra los del trimestral, y el resultado fue una serie de huecos que aparecieron de
a uno, cada uno costando una generación real:

  * el NIVEL DE REFERENCIA de cada indicador — el modelo lo ponía de memoria y el guard
    vetaba el informe entero (dos veces el 2026-08-27);
  * el SCORE de cada indicador — viajaba en la trayectoria y el balance lo tiraba;
  * la NOTA de capital redundante — el trimestral la imprime y el anual publicaba dos filas
    con el número idéntico sin explicar por qué;
  * el balance POR DIMENSIÓN — el trimestral imprime los cinco sub-componentes y el anual
    decía «el score cedió 6,02 puntos» sin poder decir por cuál.

El patrón tiene nombre en este repo —«un guard existe en un motor y falta en el otro»— pero
acá es del lado del DATO. Estos tests fijan la paridad para que el próximo hueco falle en CI
en vez de en un PDF que ya se mandó.
"""
from __future__ import annotations

from modules.banking_score.reports.pdf_generator import (_nota_de_capital_del_balance,
                                                         _nota_de_capital_redundante)
from modules.banking_score.reports.revision_anual import (_balance, _balance_por_dimension,
                                                          _reconciliacion_publica)

#: Serie REAL de Bonao 2025, tomada de la trayectoria publicada en su Deep Dive de diciembre.
SUB_REAL = {
    "solidez": [{"period_end": "2024-12-31", "score": 75.32},
                {"period_end": "2025-12-31", "score": 67.99}],
    "calidad": [{"period_end": "2024-12-31", "score": 77.54},
                {"period_end": "2025-12-31", "score": 72.15}],
    "eficiencia": [{"period_end": "2024-12-31", "score": 19.24},
                   {"period_end": "2025-12-31", "score": 11.43}],
    "liquidez": [{"period_end": "2024-12-31", "score": 61.49},
                 {"period_end": "2025-12-31", "score": 57.21}],
    "diversificacion": [{"period_end": "2024-12-31", "score": 21.91},
                        {"period_end": "2025-12-31", "score": 22.75}],
}
CORTES = ["2024-12-31", "2025-12-31"]


def test_la_descomposicion_RECONCILIA_con_el_cambio_del_score():
    """El test que vale por todos: un comité SUMA la columna.

    Con los datos reales de Bonao el score cedió 6,02 puntos, y los aportes por dimensión
    tienen que dar eso mismo. Si no reconcilia, la tabla contradice su propio titular.
    """
    rec = _reconciliacion_publica(SUB_REAL, CORTES, "aap", -6.02)
    assert rec["suma_de_aportes"] == -6.02
    assert rec["reconcilia"] is True


def test_declara_el_centesimo_del_redondeo_en_vez_de_esconderlo():
    """Las filas redondeadas suman −6,03 y el titular dice −6,02. Esconder esa diferencia es
    peor que declararla: el lector que sume a mano va a encontrarla igual."""
    rec = _reconciliacion_publica(SUB_REAL, CORTES, "aap", -6.02)
    assert rec["suma_de_las_filas_redondeadas"] == -6.03
    assert "redondeadas" in rec["nota"]


def test_el_aporte_pondera_por_el_PESO_y_no_es_el_delta_suelto():
    """Eficiencia cae MÁS que Solidez (−7,81 vs −7,33) y aporta MENOS, porque pesa 13 % contra
    38 %. Servir el delta suelto obliga al modelo a multiplicar, y multiplicar es lo que hace
    mal — por eso la doctrina manda computarlo."""
    filas = {f["dimension"]: f for f in _balance_por_dimension(SUB_REAL, CORTES, "aap")}
    assert filas["eficiencia"]["cambio"] < filas["solidez"]["cambio"]
    assert filas["eficiencia"]["aporte_al_cambio"] > filas["solidez"]["aporte_al_cambio"]


def test_ordena_de_la_que_mas_DESTRUYO_a_la_que_mas_aporto():
    filas = _balance_por_dimension(SUB_REAL, CORTES, "aap")
    assert [f["dimension"] for f in filas][0] == "solidez"
    assert [f["dimension"] for f in filas][-1] == "diversificacion"


def test_los_pesos_se_RENORMALIZAN_sobre_lo_presente():
    """Si falta una dimensión, acreditarle su peso a las demás es fabricar el dato que no
    está. Es la misma regla del motor, y sin ella los aportes no sumarían el cambio real."""
    parcial = {k: v for k, v in SUB_REAL.items() if k != "diversificacion"}
    filas = _balance_por_dimension(parcial, CORTES, "aap")
    assert abs(sum(f["peso"] for f in filas) - 1.0) < 1e-6


def test_la_nota_de_capital_del_anual_es_LA_MISMA_del_trimestral():
    """No dos textos parecidos: el mismo. Dos redacciones del mismo hecho divergen, y ya nos
    pasó con las etiquetas de tipo de entidad."""
    del_trimestral = _nota_de_capital_redundante(
        {"solvencia": {"raw": 23.26}, "leverage": {"raw": 23.26}})
    del_anual = _nota_de_capital_del_balance(
        [{"indicador": "solvencia", "cierre": 23.26},
         {"indicador": "leverage", "cierre": 23.26}])
    assert del_anual == del_trimestral
    assert del_anual is not None


def test_la_nota_NO_sale_cuando_los_dos_ratios_difieren():
    assert _nota_de_capital_del_balance(
        [{"indicador": "solvencia", "cierre": 23.26},
         {"indicador": "leverage", "cierre": 19.10}]) is None


def test_el_balance_por_indicador_lleva_referencia_Y_score():
    """Los dos huecos que costaron informes, fijados juntos: sin la referencia el guard veta,
    sin el score la tabla no deja ver qué mueve la calificación."""
    indicadores = {"cobertura_provisiones": [
        {"period_end": "2024-12-31", "raw": 147.82, "score": 66.6},
        {"period_end": "2025-12-31", "raw": 108.36, "score": 52.9}]}
    fila = _balance(indicadores, CORTES)[0]
    assert fila["nivel_de_referencia"] == 100.0
    assert (fila["score_apertura"], fila["score_cierre"]) == (66.6, 52.9)
