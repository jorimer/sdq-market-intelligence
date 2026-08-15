"""Tests de la calibración de pesos de alerta temprana.

Protegen tres cosas que ya fallaron una vez: (a) que una observación incompleta se EXCLUYA
en vez de rellenarse con ceros, (b) que una señal con coeficiente negativo reciba peso 0 y
no su valor absoluto, y (c) que el módulo no publique un vector único de pesos —el hallazgo
es que la receta los determina tanto como el dato, y un vector único lo escondería.
"""
from datetime import date

import pytest

from modules.banking_score.validation import ew_calibration as cal


def _serie(n_meses, *, mora=2.0, cob=150.0, apa=12.0, act=1000.0, dep=800.0,
           fin=date(2026, 4, 1), tipo="Bancos Múltiples"):
    """Serie mensual sana de *n_meses* terminando en *fin*."""
    out = {}
    for k in range(n_meses):
        d = cal._shift(fin, k)
        out[d] = {"tipo_entidad": tipo, "morosidad_pct": mora, "cobertura_pct": cob,
                  "apalancamiento_pct": apa, "activos_totales": act, "depositos_totales": dep}
    return out


# ── build_features: la brecha se declara, no se rellena ──

def test_features_faltante_devuelve_none_no_cero():
    s = _serie(30)
    ref = date(2025, 12, 1)
    s[ref] = dict(s[ref], cobertura_pct=None)
    assert cal.build_features(s, ref, 5.0) is None, (
        "una observación sin cobertura debe EXCLUIRSE de la matriz; rellenarla con 0 sería "
        "una brecha disfrazada de señal apagada")


def test_features_sin_referencia_12m_devuelve_none():
    s = _serie(6)
    assert cal.build_features(s, date(2026, 4, 1), 5.0) is None


def test_erosion_y_liquidez_invierten_el_signo():
    """La señal es la CAÍDA del capital y la FUGA de depósitos: deterioro ⇒ valor positivo."""
    fin = date(2026, 4, 1)
    s = _serie(30)
    s[fin] = dict(s[fin], apalancamiento_pct=9.0, depositos_totales=700.0)  # cae capital y depósitos
    fx = cal.build_features(s, fin, 5.0)
    assert fx["erosion_capital"] == pytest.approx(3.0), "capital 12→9 ⇒ erosión +3"
    assert fx["estres_liquidez"] > 0, "depósitos 800→700 ⇒ fuga positiva"


def test_morosidad_nivel_es_relativa_al_piso_del_tipo():
    s = _serie(30, mora=8.0)
    fx = cal.build_features(s, date(2026, 4, 1), cal.morosidad_floor("Bancos Múltiples"))
    assert fx["morosidad_nivel"] == pytest.approx(3.0)   # 8.0 − piso 5.0 de banca múltiple
    fx2 = cal.build_features(s, date(2026, 4, 1), cal.morosidad_floor("Corporaciones de Crédito"))
    assert fx2["morosidad_nivel"] == pytest.approx(-7.0)  # el mismo 8% es normal para su tipo


def test_brecha_provisiones_no_premia_el_exceso():
    s = _serie(30, cob=400.0)
    fx = cal.build_features(s, date(2026, 4, 1), 5.0)
    assert fx["brecha_provisiones"] == 0.0


# ── build_design: quién entra como positivo y quién como control ──

def test_entidad_viva_no_es_salida():
    panel = {"VIVO": _serie(40)}
    spec = cal.CohortSpec("t", False, False, 12)
    _, y, _ = cal.build_design(panel, spec, date(2026, 4, 1))
    assert sum(y) == 0, "una entidad que reporta hasta el final del panel no salió del sistema"


def test_salida_entra_como_positivo():
    panel = {"SALE": _serie(40, fin=date(2020, 1, 1))}
    spec = cal.CohortSpec("t", False, False, 12)
    _, y, _ = cal.build_design(panel, spec, date(2026, 4, 1))
    assert sum(y) == 1


def test_solo_agudas_excluye_al_zombi_cronico():
    """Una entidad ya podrida 24m antes de salir no es una alerta TEMPRANA: es insolvencia
    crónica. Con ``solo_agudas`` no debe entrar como positivo."""
    fin = date(2020, 1, 1)
    s = _serie(40, fin=fin)
    s[cal._shift(fin, cal.LOOKBACK_SANO_M)] = dict(
        s[cal._shift(fin, cal.LOOKBACK_SANO_M)], morosidad_pct=30.0)
    panel = {"ZOMBI": s}
    _, y_todas, _ = cal.build_design(panel, cal.CohortSpec("t", False, False, 12), date(2026, 4, 1))
    _, y_agudas, _ = cal.build_design(panel, cal.CohortSpec("t", True, False, 12), date(2026, 4, 1))
    assert sum(y_todas) == 1 and sum(y_agudas) == 0


def test_controles_solo_supervivientes_excluye_el_pasado_de_las_que_salieron():
    panel = {"SALE": _serie(120, fin=date(2020, 1, 1)), "VIVO": _serie(120)}
    todos = cal.build_design(panel, cal.CohortSpec("t", False, False, 12), date(2026, 4, 1))
    sup = cal.build_design(panel, cal.CohortSpec("t", False, True, 12), date(2026, 4, 1))
    n_ctrl_todos = sum(1 for v in todos[1] if v == 0)
    n_ctrl_sup = sum(1 for v in sup[1] if v == 0)
    assert n_ctrl_sup < n_ctrl_todos


def test_control_no_puede_estar_dentro_del_deterioro_terminal():
    """Ningún control debe caer a menos de SAFE_GAP+horizonte de su propia salida."""
    fin = date(2020, 1, 1)
    panel = {"SALE": _serie(200, fin=fin)}
    spec = cal.CohortSpec("t", False, False, 12)
    _, y, _ = cal.build_design(panel, spec, date(2026, 4, 1))
    # el único positivo es la salida; los controles vienen de años muy anteriores
    assert sum(y) == 1 and len(y) > 1


# ── fit_weights: el signo importa ──

def test_coeficiente_negativo_recibe_peso_cero_no_su_valor_absoluto():
    """Una señal que apunta al revés en la cohorte no puede APORTAR peso a un índice de
    deterioro. Tomarle el valor absoluto la premiaría por estar mal."""
    import random
    random.seed(7)
    X, y, g = [], [], []
    for i in range(80):
        pos = i % 4 == 0
        # feature 0 apunta al REVÉS (alta en los sanos); feature 5 apunta bien
        X.append([5.0 if not pos else 0.0, 0, 0, 0, 0, 5.0 if pos else 0.0])
        y.append(1 if pos else 0)
        g.append(f"E{i%10}")
    r = cal.fit_weights(X, y, g, cal.CohortSpec("t", True, True, 12))
    assert r is not None
    assert r.coef["morosidad_nivel"] < 0
    assert r.weights["morosidad_nivel"] == 0.0
    assert r.weights["estres_liquidez"] > 0


def test_pocos_positivos_devuelve_none():
    X = [[0.0] * 6 for _ in range(20)]
    y = [1] * 3 + [0] * 17
    g = [f"E{i}" for i in range(20)]
    assert cal.fit_weights(X, y, g, cal.CohortSpec("t", True, True, 12)) is None


def test_pesos_suman_uno_cuando_hay_coeficientes_positivos():
    X, y, g = [], [], []
    for i in range(80):
        pos = i % 4 == 0
        X.append([5.0 if pos else 0.0, 0, 0, 0, 0, 3.0 if pos else 0.0])
        y.append(1 if pos else 0)
        g.append(f"E{i%10}")
    r = cal.fit_weights(X, y, g, cal.CohortSpec("t", True, True, 12))
    assert sum(r.weights.values()) == pytest.approx(1.0, abs=1e-3)


# ── el contrato del módulo: NO hay vector canónico ──

def test_el_modulo_no_publica_un_vector_unico_de_pesos():
    """El hallazgo es que la receta determina los pesos tanto como el dato. Si alguien
    agrega acá un ``CALIBRATED_WEIGHTS`` fijo, vuelve a esconderlo — y volvemos a tener
    siete decimales sin respaldo, que es exactamente lo que este módulo vino a corregir."""
    prohibidos = [n for n in dir(cal)
                  if n.isupper() and "WEIGHT" in n and isinstance(getattr(cal, n), dict)]
    assert not prohibidos, (
        f"{prohibidos}: la salida canónica es sensitivity_table(), no un vector fijo")


def test_sensitivity_table_devuelve_una_fila_por_receta_evaluable():
    panel = {f"E{i}": _serie(140, fin=date(2020, 1, 1) if i % 3 == 0 else date(2026, 4, 1),
                             mora=2.0 + i % 5, apa=12.0 - (i % 3))
             for i in range(30)}
    res = cal.sensitivity_table(panel, panel_end=date(2026, 4, 1))
    assert len(res) >= 1
    assert all(set(r.weights) == set(cal.FEATURES) for r in res)
    txt = cal.format_table(res)
    assert "receta de cohorte" in txt and "AUC" in txt


def test_solvencia_no_esta_en_las_features():
    """Límite declarado: Basilea es regulatoria y no existe pre-2004. Su peso vigente (0.06)
    NO es verificable con esta fuente, y la matriz no debe fingir que lo verifica."""
    assert not any("solvencia" in f for f in cal.FEATURES)
