"""Tests de las funciones PURAS del backtest de resultado-proxy del ISA (sin DB).

Verifican: la ventana prospectiva, la etiqueta de subdesempeño relativo (vs. mediana del
panel), los quintiles y el sentido del Gini (score bajo que subdesempeña → Gini > 0).
"""
from modules.pension_intel.validation.backtest import (
    Obs,
    _quintile_tiers,
    derive_observations,
    forward_mean,
    summarize_signal,
)


def test_forward_mean_solo_periodos_posteriores():
    r = [("2020-01", 1.0), ("2020-02", 2.0), ("2020-03", 3.0), ("2020-04", 9.0)]
    # base 2020-02 → toma 2020-03, 2020-04 (posteriores), horizonte 2 → media (3+9)/2
    assert forward_mean(r, "2020-02", 2) == 6.0
    assert forward_mean(r, "2020-04", 2) is None  # nada posterior


# Panel sintético: 5 AFP, el score MÁS BAJO tiene el retorno prospectivo MÁS BAJO.
_SCORES = {s: {"2019-12": v, "2020-12": v} for s, v in
           {"a": 0.1, "b": 0.2, "c": 0.3, "d": 0.4, "e": 0.5}.items()}
_RETS = {s: [(f"2021-{m:02d}", base) for m in range(1, 13)] for s, base in
         {"a": 1.0, "b": 2.0, "c": 3.0, "d": 4.0, "e": 5.0}.items()}


def test_derive_labels_por_mediana_del_panel():
    obs = derive_observations(_SCORES, _RETS, horizon=12)
    assert len(obs) == 10  # 5 AFP × 2 períodos base
    by = {(o.slug, o.period): o for o in obs}
    # mediana del panel = 3.0 (c); por debajo → label 1 = a, b
    assert by[("a", "2019-12")].label == 1
    assert by[("b", "2019-12")].label == 1
    assert by[("c", "2019-12")].label == 0  # la mediana no está "por debajo"
    assert by[("e", "2020-12")].label == 0


def test_min_afps_descarta_periodos_ralos():
    thin = {"a": {"2019-12": 0.1}, "b": {"2019-12": 0.2}}  # solo 2 AFP en t
    assert derive_observations(thin, _RETS, horizon=12, min_afps=3) == []


def test_quintiles_ordenan_de_menor_a_mayor():
    tiers = _quintile_tiers([0.5, 0.1, 0.3, 0.4, 0.2])
    assert tiers[1].startswith("Q1")  # el 0.1 (más bajo) cae en Q1
    assert tiers[0].startswith("Q5")  # el 0.5 (más alto) cae en Q5


def test_gini_positivo_cuando_score_bajo_subdesempena():
    rep = summarize_signal(derive_observations(_SCORES, _RETS, horizon=12))
    assert rep is not None
    assert rep["gini"] > 0.9          # discriminación casi perfecta por construcción
    assert rep["n_obs"] == 10
    assert rep["conclusive"] is True  # IC no cruza 0


def test_gini_negativo_cuando_score_alto_subdesempena():
    # invertido: el score alto rinde peor → el score NO discrimina bien el riesgo
    inv_ret = {s: [(f"2021-{m:02d}", base) for m in range(1, 13)] for s, base in
               {"a": 5.0, "b": 4.0, "c": 3.0, "d": 2.0, "e": 1.0}.items()}
    rep = summarize_signal(derive_observations(_SCORES, inv_ret, horizon=12))
    assert rep is not None and rep["gini"] < 0


def test_pocas_obs_o_una_sola_clase_devuelve_none():
    assert summarize_signal([Obs("a", "2020-12", 0.5, 1.0, 0)]) is None  # < 8 obs
    same = [Obs(f"x{i}", "2020-12", 0.1 * i, 1.0, 0) for i in range(10)]
    assert summarize_signal(same) is None  # una sola clase (todas label 0)
