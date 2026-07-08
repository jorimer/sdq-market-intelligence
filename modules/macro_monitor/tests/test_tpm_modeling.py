"""Tests del modelo de predicción de TPM: panel point-in-time, regla de Taylor,
clasificador (imbalance) y backtest time-series. Sin DB ni red (piezas puras +
monkeypatch de los dos cargadores)."""
from datetime import date

import numpy as np
import pytest

from modules.macro_monitor.tpm_modeling import backtest as bt
from modules.macro_monitor.tpm_modeling import dataset as ds
from modules.macro_monitor.tpm_modeling import features as F
from modules.macro_monitor.tpm_modeling.classifier import (
    TpmClassifier,
    _sample_weights,
    build_xy,
)
from modules.macro_monitor.tpm_modeling.reaction_function import fit_reaction_function

FEATS = F.FEATURE_NAMES


# ── features ──────────────────────────────────────────────────────
def test_hp_filter_smooths_and_short_series_passthrough():
    # Serie con ruido alrededor de una tendencia lineal → la tendencia HP es más suave.
    x = np.arange(60, dtype=float)
    y = 0.5 * x + np.sin(x) * 3
    trend = F.hp_filter(y)
    assert trend.shape == y.shape
    assert trend.std() < y.std()          # la tendencia varía menos que la serie
    # < 3 puntos: passthrough sin filtrar
    assert np.allclose(F.hp_filter(np.array([1.0, 2.0])), np.array([1.0, 2.0]))


def test_output_gap_sign_and_insufficient():
    # Índice que sube y luego salta por encima de la tendencia → brecha positiva al final.
    idx = list(np.linspace(90, 100, 24)) + [110.0]
    gap = F.output_gap_last(idx)
    assert gap is not None and gap > 0
    assert F.output_gap_last([100.0, 101.0]) is None  # < 3 obs


def test_inflation_gap_and_yoy():
    assert F.inflation_gap(6.0) == 2.0        # 6% − meta 4%
    assert F.inflation_gap(None) is None
    assert F.yoy(110, 100) == pytest.approx(10.0)
    assert F.yoy(100, 0) is None              # divisor cero → None


# ── dataset: point-in-time (anti look-ahead) ──────────────────────
def test_series_latest_available_respects_publication_lag():
    obs = [("2020-03", 1.0), ("2020-04", 2.0), ("2020-05", 3.0)]
    s = ds._Series(obs, lag_days=45)  # abril cierra 30/4, disponible ~14/6
    # Al 2020-06-10 abril AÚN no está publicado (30/4 + 45d = 14/6) → última es marzo.
    assert s.latest_available(date(2020, 6, 10)) == ("2020-03", 1.0)
    # Al 2020-06-20 abril ya está disponible.
    assert s.latest_available(date(2020, 6, 20)) == ("2020-04", 2.0)
    # Antes de todo: None.
    assert s.latest_available(date(2020, 1, 1)) is None


def test_series_history_until_no_future_leak():
    obs = [("2020-03", 1.0), ("2020-04", 2.0), ("2020-05", 3.0)]
    s = ds._Series(obs, lag_days=15)
    hist = s.history_until(date(2020, 5, 1))  # abril (30/4+15=15/5) aún no; marzo sí
    assert hist == [1.0]


def test_shift_months():
    assert ds._shift_months("2020-01", -12) == "2019-01"
    assert ds._shift_months("2020-03", -1) == "2020-02"
    assert ds._shift_months("2020-12", 1) == "2021-01"


def test_build_panel_threads_previous_level(monkeypatch):
    # Dos "series" mínimas y tres decisiones; verifica que tpm_prev = nivel de la previa.
    decisions = [
        (date(2020, 1, 31), "hold", 4.0),
        (date(2020, 2, 29), "hike", 4.5),
        (date(2020, 3, 31), "cut", 4.0),
    ]
    monkeypatch.setattr(ds, "_decisions_asc", lambda db: decisions)
    monkeypatch.setattr(ds, "_load_series", lambda db: {
        c: ds._Series([], lag) for c, lag in ds.PUBLICATION_LAG_DAYS.items()
    })
    rows = ds.build_panel(db=None)
    assert [r.tpm_prev for r in rows] == [None, 4.0, 4.5]
    assert [r.action for r in rows] == ["hold", "hike", "cut"]


# ── reaction function ─────────────────────────────────────────────
def _panel_from(specs):
    """specs: lista de dicts con features + tpm_level + action → PanelRow."""
    out = []
    for i, sp in enumerate(specs):
        feats = {n: sp.get(n) for n in FEATS}
        out.append(ds.PanelRow(as_of=date(2010, 1, 1),
                               action=sp.get("action", "hold"),
                               tpm_level=sp.get("tpm_level"),
                               tpm_prev=sp.get("tpm_lag"),
                               features=feats))
    return out


def test_reaction_function_recovers_coefficients():
    rng = np.random.default_rng(0)
    rows = []
    for _ in range(60):
        ig = float(rng.uniform(-3, 3))
        og = float(rng.uniform(-4, 4))
        lag = float(rng.uniform(3, 9))
        level = 1.0 + 0.5 * ig + 0.3 * og + 0.4 * lag  # relación exacta
        rows.append(_panel_from([{
            "inflation_gap": ig, "output_gap": og, "tpm_lag": lag, "real_rate": 0.0,
            "fx_yoy": 0.0, "reserves_yoy": 0.0, "m1_yoy": 0.0, "tpm_level": level,
        }])[0])
    rf = fit_reaction_function(rows)
    assert rf.r2 > 0.999
    assert rf.coefficients["inflation_gap"] == pytest.approx(0.5, abs=0.02)
    assert rf.coefficients["tpm_lag"] == pytest.approx(0.4, abs=0.02)
    # predict / bias
    feats = {"inflation_gap": 2.0, "output_gap": 0.0, "tpm_lag": 5.0}
    assert rf.predict(feats) == pytest.approx(1.0 + 0.5 * 2 + 0.4 * 5, abs=0.05)
    assert rf.bias(feats, current_tpm=5.0) == pytest.approx(rf.predict(feats) - 5.0, abs=1e-6)
    assert rf.predict({"inflation_gap": None, "output_gap": 0.0, "tpm_lag": 5.0}) is None


def test_reaction_function_roundtrip():
    rows = _panel_from([{"inflation_gap": i * 0.1, "output_gap": 0.0, "tpm_lag": 5.0,
                         "tpm_level": 5.0 + i * 0.05} for i in range(20)])
    rf = fit_reaction_function(rows)
    from modules.macro_monitor.tpm_modeling.reaction_function import ReactionFunction
    rf2 = ReactionFunction.from_dict(rf.to_dict())
    feats = {"inflation_gap": 1.0, "output_gap": 0.0, "tpm_lag": 5.0}
    assert rf2.predict(feats) == pytest.approx(rf.predict(feats), abs=1e-9)


def test_reaction_function_insufficient_data_raises():
    with pytest.raises(ValueError):
        fit_reaction_function(_panel_from([{"inflation_gap": 1.0, "output_gap": 0.0,
                                            "tpm_lag": 5.0, "tpm_level": 5.0}]))


# ── clasificador + imbalance ──────────────────────────────────────
def _labeled_rows(n=150, seed=1):
    rng = np.random.default_rng(seed)
    rows = []
    for _ in range(n):
        ig = float(rng.uniform(-3, 3))
        action = "hike" if ig > 1.2 else "cut" if ig < -1.2 else "hold"
        rows.append(_panel_from([{
            "inflation_gap": ig, "output_gap": float(rng.uniform(-2, 2)),
            "real_rate": float(rng.uniform(-2, 2)), "tpm_lag": 5.0,
            "fx_yoy": 0.0, "reserves_yoy": 0.0, "m1_yoy": 0.0,
            "action": action, "tpm_level": 5.0,
        }])[0])
    return rows


def test_build_xy_drops_incomplete_rows():
    rows = _labeled_rows(10)
    rows.append(_panel_from([{"inflation_gap": None, "output_gap": 0.0, "real_rate": 0.0,
                              "tpm_lag": 5.0, "fx_yoy": 0.0, "reserves_yoy": 0.0,
                              "m1_yoy": None, "action": "hold"}])[0])
    X, y = build_xy(rows)
    assert len(X) == 10 and len(y) == 10   # la fila con None se descarta


def test_sample_weights_balance_classes():
    # 8 de clase 0, 2 de clase 1 → la clase rara pesa más por ejemplo.
    y_idx = np.array([0] * 8 + [1] * 2)
    w = _sample_weights(y_idx, n_classes=2)
    assert w[y_idx == 1].mean() > w[y_idx == 0].mean()
    # peso ∝ 1/frecuencia: total balanceado por clase
    assert w[y_idx == 0].sum() == pytest.approx(w[y_idx == 1].sum(), rel=1e-6)


def test_classifier_learns_separable_signal():
    clf = TpmClassifier().fit(*build_xy(_labeled_rows(200)))
    hike = clf.predict_proba({"inflation_gap": 2.5, "output_gap": 0.0, "real_rate": 0.0,
                              "tpm_lag": 5.0, "fx_yoy": 0.0, "reserves_yoy": 0.0, "m1_yoy": 0.0})
    assert max(hike, key=hike.get) == "hike"
    cut = clf.predict_proba({"inflation_gap": -2.5, "output_gap": 0.0, "real_rate": 0.0,
                             "tpm_lag": 5.0, "fx_yoy": 0.0, "reserves_yoy": 0.0, "m1_yoy": 0.0})
    assert max(cut, key=cut.get) == "cut"
    # features incompletas → None
    assert clf.predict_proba({"inflation_gap": None}) is None


def test_classifier_serialize_roundtrip():
    clf = TpmClassifier().fit(*build_xy(_labeled_rows(120)))
    clf2 = TpmClassifier.deserialize(clf.serialize())
    feats = {"inflation_gap": 2.5, "output_gap": 0.0, "real_rate": 0.0, "tpm_lag": 5.0,
             "fx_yoy": 0.0, "reserves_yoy": 0.0, "m1_yoy": 0.0}
    assert clf2.predict_proba(feats) == clf.predict_proba(feats)


# ── backtest time-series ──────────────────────────────────────────
def _timeseries_panel(n=140):
    """Panel cronológico con nivel + acción derivados de la brecha de inflación."""
    from datetime import timedelta
    rng = np.random.default_rng(3)
    rows = []
    d = date(2008, 1, 31)
    lag = 5.0
    for _ in range(n):
        ig = float(rng.uniform(-3, 3))
        action = "hike" if ig > 1.0 else "cut" if ig < -1.0 else "hold"
        level = 5.0 + 0.3 * ig
        rows.append(ds.PanelRow(as_of=d, action=action, tpm_level=level, tpm_prev=lag,
                                features={"inflation_gap": ig, "output_gap": float(rng.uniform(-2, 2)),
                                          "real_rate": lag - (ig + 4), "tpm_lag": lag,
                                          "fx_yoy": 0.0, "reserves_yoy": 0.0, "m1_yoy": 0.0}))
        lag = level
        d = d + timedelta(days=30)
    return rows


def test_backtest_is_expanding_window_with_baseline():
    rep = bt.run_backtest(_timeseries_panel(), min_train=60)
    c = rep["classifier"]
    assert c["ok"] is True
    assert c["n_test"] > 0
    # baseline "siempre hold" reportado y comparado
    assert "baseline_always_hold_accuracy" in c
    assert set(c["per_class"]) == {"cut", "hold", "hike"}
    assert c["confusion_matrix"]["labels"] == ["cut", "hold", "hike"]
    # señal separable → debe superar el baseline y tener recall en minoritarias
    assert c["beats_baseline"] is True
    assert c["per_class"]["hike"]["recall"] > 0.5

    r = rep["reaction_function"]
    assert r["ok"] is True
    assert r["mae_nivel"] >= 0
    assert "horizonte_6m" in r["direccional"] and "horizonte_12m" in r["direccional"]


def test_backtest_insufficient_panel_reports_reason():
    rep = bt.run_backtest(_timeseries_panel(30), min_train=60)
    assert rep["classifier"]["ok"] is False
    assert "reason" in rep["classifier"]
