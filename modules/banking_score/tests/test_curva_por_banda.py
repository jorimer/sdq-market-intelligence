"""La curva por banda: si no ordena el riesgo, no se presenta como si lo hiciera.

**El caso.** El reporte publicaba esta tabla (mejor → peor): Sólida 23,1 % (n=516) ·
Adecuada 13,7 % · En vigilancia 9,9 % · Frágil 27,6 %. Es una U, no una curva creciente: la
banda SUPERIOR, con el N más grande del panel, tiene más deterioro realizado que las dos
siguientes. Y el caveat automático lo llamaba «ruido muestral en tiers intermedios» — una
frase fija que describe otro defecto, en otro lugar de la tabla, con otro tamaño de muestra.

Dos reglas, y la segunda es la que evita que vuelva:

1. El caveat NOMBRA la inversión concreta —qué bandas, con qué tasas y qué N—, computada del
   propio resultado. Las relaciones se computan; el texto las copia.
2. El reporte publica `by_tier_ordena_riesgo`, para que la superficie que dibuja la tabla no
   tenga que deducirlo. Una deducción se pierde en el camino a un PDF o a una lámina.
"""
from modules.banking_score.validation.report import _caveat_de_monotonia, build_backtest_report
from shared.validation.metrics import monotonicity_violations

# La curva REAL de producción al 2026-08-19, ordenada mejor → peor.
_CURVA_PROD = [
    {"tier": "Sólida", "n": 516, "events": 119, "rate": 119 / 516},
    {"tier": "Adecuada", "n": 819, "events": 112, "rate": 112 / 819},
    {"tier": "En vigilancia", "n": 162, "events": 16, "rate": 16 / 162},
    {"tier": "Frágil", "n": 196, "events": 54, "rate": 54 / 196},
]


def test_la_inversion_se_detecta_en_la_banda_superior_no_en_los_tiers_intermedios():
    v = monotonicity_violations(_CURVA_PROD)
    assert v, "La curva de producción es una U: tiene que reportar inversiones."
    peor = v[0]
    assert peor["mejor"] == "Sólida" and peor["peor"] == "Adecuada"
    assert peor["mejor_n"] == 516  # el N más grande del panel, no una muestra chica


def test_el_caveat_nombra_la_banda_real_y_su_n():
    texto = _caveat_de_monotonia(monotonicity_violations(_CURVA_PROD))
    assert "Sólida" in texto and "n=516" in texto
    assert "23,1 %" in texto and "13,7 %" in texto   # coma decimal: el reporte se lee en español
    assert "tiers intermedios" not in texto.replace("no es ruido de un tier intermedio", "")


def test_una_curva_creciente_no_produce_caveat_de_monotonia():
    creciente = [
        {"tier": "Sólida", "n": 100, "events": 5, "rate": 0.05},
        {"tier": "Adecuada", "n": 100, "events": 10, "rate": 0.10},
        {"tier": "Frágil", "n": 100, "events": 30, "rate": 0.30},
    ]
    assert monotonicity_violations(creciente) == []


def test_el_reporte_declara_si_la_curva_ORDENA_el_riesgo(monkeypatch):
    """`by_tier_ordena_riesgo` viaja en la respuesta: la superficie no lo deduce."""
    from modules.banking_score.validation import report as mod

    class _Obs:
        def __init__(self, score, tier, det):
            self.score, self.tier, self.deteriorated = score, tier, det

    # Panel sintético con la MISMA forma de U que producción: la banda superior se deteriora
    # más que la siguiente.
    obs = ([_Obs(90.0, "Sólida", True)] * 6 + [_Obs(90.0, "Sólida", False)] * 14 +
           [_Obs(70.0, "Adecuada", True)] * 2 + [_Obs(70.0, "Adecuada", False)] * 18 +
           [_Obs(50.0, "En vigilancia", True)] * 3 + [_Obs(50.0, "En vigilancia", False)] * 17 +
           [_Obs(30.0, "Frágil", True)] * 8 + [_Obs(30.0, "Frágil", False)] * 12)
    monkeypatch.setattr(mod, "derive_observations", lambda *_a, **_k: obs)

    rep = build_backtest_report(db=None, n_boot=50)
    assert rep["ok"] is True
    assert rep["monotonic"] is False
    assert rep["by_tier_ordena_riesgo"] is False
    assert rep["monotonic_violations"], "La U tiene que quedar declarada, no solo negada."
    assert "Sólida" in rep["caveats"][0]
