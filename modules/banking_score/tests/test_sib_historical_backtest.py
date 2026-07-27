"""Tests del backtest de Alerta Temprana sobre el histórico SIB.

Validan el criterio de *cluster* (una alerta alta suelta y crónica NO fecha un inicio;
la convergencia de ≥2 altas sí) y el cálculo de anticipación, con datos sintéticos
deterministas.
"""
from datetime import date
from types import SimpleNamespace

from modules.banking_score import sib_historical_backtest as bt


def _months(n, start_year=2020):
    out = []
    y, m = start_year, 1
    for _ in range(n):
        out.append(date(y, m, 1))
        m += 1
        if m > 12:
            m, y = 1, y + 1
    return out


def _row(fecha, *, mora, cob, activos=1000.0, dep=600.0, liq=300.0, pas=850.0):
    return SimpleNamespace(
        fecha=fecha, entidad_nombre="Banco Test", entidad_code="TEST",
        activos_totales=activos, depositos_totales=dep, activos_liquidos=liq,
        pasivos_totales=pas, cobertura_pct=cob, morosidad_pct=mora,
    )


def _series(specs):
    ds = _months(len(specs))
    return {d: _row(d, **s) for d, s in zip(ds, specs)}


def test_cluster_onset_and_lead():
    """12 meses sanos, luego deterioro agudo (morosidad salta, cobertura se hunde):
    dos alertas altas convergen → onset en el mes del salto."""
    healthy = [dict(mora=1.0, cob=200.0)] * 12
    bad = [dict(mora=40.0, cob=20.0)] * 6           # 2021-01 … 2021-06
    series = _series(healthy + bad)
    r = bt.backtest_entity(series, salida=date(2021, 6, 1))
    assert r["onset_cluster"] == "2021-01-01"       # primer mes con ≥2 altas
    assert r["lead_months"] == 5                     # ene→jun 2021
    # el cluster incluye salto de morosidad y brecha de provisiones
    cluster = next(t for t in r["timeline"] if t["period"] == "2021-01-01")
    codes = {a["code"] for a in cluster["alerts"] if a["severity"] == "alta"}
    assert {"salto_morosidad", "brecha_provisiones"} <= codes


def test_chronic_single_alert_is_not_onset():
    """Una cobertura crónicamente baja (una sola alerta alta persistente) NO fecha un
    inicio: sin salto de morosidad no hay cluster → onset None. Es el filtro anti-ruido."""
    series = _series([dict(mora=1.0, cob=20.0)] * 18)  # cobertura baja siempre, mora plana
    r = bt.backtest_entity(series, salida=date(2021, 6, 1))
    assert r["first_high_raw"] is not None            # sí hay alertas altas sueltas…
    assert r["onset_cluster"] is None                 # …pero nunca un cluster
    assert r["lead_months"] is None


def test_healthy_series_no_alerts():
    series = _series([dict(mora=1.0, cob=200.0)] * 18)
    r = bt.backtest_entity(series, salida=date(2021, 6, 1))
    assert r["onset_cluster"] is None
    assert r["n_high_months"] == 0
