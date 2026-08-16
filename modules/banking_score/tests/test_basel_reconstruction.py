"""Tests de la solvencia Basilea reconstruida.

El riesgo de esta serie no es que calcule mal: es que alguien la use como si fuera el ratio
regulatorio. Estos tests protegen el error medido, la etiqueta y —sobre todo— que no se
cablee a una regla de umbral más fina que su propio error.
"""
from types import SimpleNamespace

import pytest

from modules.banking_score import sib_basel_reconstruction as br


def _l(n1, n2, n3, monto):
    return SimpleNamespace(estado="situacion", nivel_1=n1, nivel_2=n2, nivel_3=n3,
                           nivel_4=n3, monto=monto)


def _banco(*, caja=100.0, cartera=1000.0, capital=150.0, resultado=50.0, intang=10.0,
           subord=0.0, cont=0.0):
    return [
        _l("Activos", "Efectivo y equivalentes de efectivo", "Caja", caja),
        _l("Activos", "Cartera de créditos", "Vigentes", cartera),
        _l("Activos", "Otros activos", "Intangibles", intang),
        _l("Activos", "Total", "Total", caja + cartera + intang),
        _l("Patrimonio", "Patrimonio neto", "Capital pagado", capital),
        _l("Patrimonio", "Patrimonio neto", "Resultados del ejercicio", resultado),
        _l("Pasivos", "Obligaciones asimilables de capital", "Obligaciones subordinadas", subord),
        _l("Cuentas contingentes", "Cuentas contingentes", "Cuentas contingentes", cont),
    ]


def test_caja_no_pondera_y_cartera_pondera_pleno():
    r = br.reconstruir(_banco(caja=500.0, cartera=1000.0, cont=0.0))
    assert r.apr == pytest.approx(1000.0), "la caja pondera 0%; solo la cartera entra al APR"


def test_resultado_del_ejercicio_queda_fuera_del_capital_primario():
    """La utilidad no auditada no computa — el ajuste sobre el solape lo llevó a cero en las
    cuatro variantes y la norma prudencial lo justifica por separado."""
    con = br.reconstruir(_banco(resultado=500.0))
    sin = br.reconstruir(_banco(resultado=0.0))
    assert con.patrimonio_tecnico == sin.patrimonio_tecnico


def test_intangibles_se_deducen_del_capital_y_no_ponderan():
    con = br.reconstruir(_banco(intang=100.0))
    sin = br.reconstruir(_banco(intang=0.0))
    assert con.patrimonio_tecnico == pytest.approx(sin.patrimonio_tecnico - 100.0)
    assert con.apr == pytest.approx(sin.apr), "un intangible se deduce del capital, no pondera"


def test_capital_secundario_topea_en_el_primario():
    r = br.reconstruir(_banco(capital=100.0, intang=0.0, subord=10_000.0))
    assert r.patrimonio_tecnico == pytest.approx(200.0), "secundario ≤ primario"


def test_contingentes_entran_con_factor_de_conversion():
    con = br.reconstruir(_banco(cont=1000.0))
    sin = br.reconstruir(_banco(cont=0.0))
    assert con.apr == pytest.approx(sin.apr + 1000.0 * br.CCF_CONTINGENTES)


def test_sin_activos_ponderables_devuelve_none_no_cero():
    assert br.reconstruir([_l("Activos", "Efectivo y equivalentes de efectivo", "Caja", 100.0)]) is None
    assert br.reconstruir([]) is None


# ── lo que protege el uso, no el cálculo ──

def test_nunca_es_apta_para_umbral():
    r = br.reconstruir(_banco())
    assert r.apta_para_umbral is False


def test_el_error_viaja_con_la_cifra_y_depende_del_tipo():
    bm = br.reconstruir(_banco(), bank_type="banca_multiple")
    aap = br.reconstruir(_banco(), bank_type="aap")
    assert bm.error_p90_pp == br.ERROR_P90_PP["banca_multiple"]
    assert aap.error_p90_pp > bm.error_p90_pp
    assert br.reconstruir(_banco(), bank_type="desconocido").error_p90_pp == br.ERROR_P90_DEFAULT


def test_el_rango_es_mas_ancho_que_la_distancia_al_minimo_regulatorio():
    """La razón por la que esta serie no puede decidir un umbral: su intervalo se come la
    distancia entre el 12% de SOLV_WARN y el 10% regulatorio."""
    from modules.banking_score.early_warning import SOLV_HIGH, SOLV_WARN
    assert br.UMBRAL_MINIMO_LEGIBLE_PP > (SOLV_WARN - SOLV_HIGH)


def test_la_etiqueta_declara_procedencia_rango_y_veto_de_comparacion():
    r = br.reconstruir(_banco(), bank_type="banca_multiple")
    txt = br.etiqueta(r)
    assert "reconstruida" in txt and "Basilea I" in txt
    assert "±" in txt and "pp" in txt
    assert "regulatorio" in txt, "debe decir que NO se compara contra el mínimo regulatorio"
    assert "%" in txt


def test_la_reconstruccion_no_esta_cableada_al_motor_de_alerta_temprana():
    """Guard estructural: si alguien importa esto desde ``early_warning``, la serie pasó a
    alimentar reglas de umbral y el error medido dejó de estar declarado en el camino."""
    import ast
    import pathlib
    ew = pathlib.Path(br.__file__).with_name("early_warning.py").read_text(encoding="utf-8")
    # Se veta el IMPORT, no la mención: el motor puede —y debe— explicar en un comentario por
    # qué la reconstrucción NO lo alimenta. Un guard que prohíbe nombrar la cosa impide
    # documentar la decisión, que es lo contrario de lo que se busca.
    importa = False
    for nodo in ast.walk(ast.parse(ew)):
        if isinstance(nodo, ast.ImportFrom) and "sib_basel_reconstruction" in (nodo.module or ""):
            importa = True
        if isinstance(nodo, ast.Import):
            importa = importa or any("sib_basel_reconstruction" in a.name for a in nodo.names)
    assert not importa, (
        "la solvencia reconstruida no puede alimentar rule_solvency: su p90 (4.6 pp en el "
        "mejor tipo) es más ancho que la banda 10.5–12% que la regla discrimina")
