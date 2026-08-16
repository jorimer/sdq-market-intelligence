"""Tests del modelo de propensión a la quiebra.

Lo que protegen no es la aritmética: es que el modelo NO PUEDA afirmar más de lo que su
validación sostiene. Publicar un porcentaje que el nivel no respalda es el fallo que este
módulo existe para impedir.
"""
from modules.banking_score import propension_quiebra as pq
from modules.banking_score.validation.ew_calibration import FEATURES


def _modelo(**kw):
    base = dict(features=tuple(FEATURES), coef={}, intercepto=0.0, media=(), escala=(),
                tasa_base=0.018, n_periodos=1000, n_eventos=20, n_entidades=30,
                auc=None, auc_ic95=None, brier=None, brier_constante=None)
    return pq.ModeloPropension(**{**base, **kw})


def test_sin_graduar_no_admite_ningun_uso():
    m = _modelo(auc=0.60, auc_ic95=(0.51, 0.70), ordena=False)
    assert "ninguno" in m.uso_admitido


def test_gradua_ordenando_pero_sin_nivel_solo_admite_ORDENAMIENTO():
    """El caso peligroso: el modelo ordena bien y alguien publica su cifra como si fuera una
    probabilidad. El uso admitido tiene que decirlo con todas las letras."""
    m = _modelo(auc=0.75, auc_ic95=(0.66, 0.84), ordena=True, nivel_confiable=False)
    assert "ORDENAMIENTO" in m.uso_admitido
    assert "NO publicar" in m.uso_admitido


def test_con_nivel_la_propension_es_por_BANDA_no_puntual():
    """Aun calibrado, el nivel solo se sostiene en el decil superior: en el medio, con ~2
    eventos por decil, lo que se mide es ruido."""
    m = _modelo(auc=0.75, auc_ic95=(0.66, 0.84), ordena=True, nivel_confiable=True)
    assert "BANDA" in m.uso_admitido and "no como probabilidad puntual" in m.uso_admitido


def test_evaluar_devuelve_SIEMPRE_el_uso_admitido_junto_a_la_cifra():
    """Un consumidor no debería poder tomar el número sin saber qué puede afirmar con él —
    la misma disciplina que el error que viaja con la solvencia reconstruida."""
    m = _modelo(auc=0.75, auc_ic95=(0.66, 0.84), ordena=True, nivel_confiable=False,
                coef={f: 0.1 for f in FEATURES} | {f"{a}×{b}": 0.0 for a, b, _ in pq.INTERACCIONES},
                media=tuple(0.0 for _ in range(len(FEATURES) + len(pq.INTERACCIONES))),
                escala=tuple(1.0 for _ in range(len(FEATURES) + len(pq.INTERACCIONES))))
    r = pq.evaluar(m, {f: 0.0 for f in FEATURES})
    assert "uso_admitido" in r and r["propension"] is not None
    assert r["publicable_como_probabilidad"] is False


def test_un_modelo_sin_entrenar_no_inventa_una_cifra():
    r = pq.evaluar(_modelo(motivo="eventos insuficientes"), {f: 1.0 for f in FEATURES})
    assert r["propension"] is None and r["motivo"]


def test_las_interacciones_tienen_un_mecanismo_declarado():
    """No se cruzan todas contra todas: con 26 eventos, quince interacciones sobreajustan
    garantizado. Cada par está porque hay una razón para esperar que uno dependa del otro."""
    assert len(pq.INTERACCIONES) <= 4
    for a, b, razon in pq.INTERACCIONES:
        assert a in FEATURES and b in FEATURES
        assert razon and len(razon) > 8, "cada interacción declara su mecanismo"


def test_la_matriz_agrega_las_interacciones_con_su_nombre():
    X, nombres = pq._matriz([[1.0, 2.0, 3.0, 4.0, 5.0, 6.0]])
    assert len(nombres) == len(FEATURES) + len(pq.INTERACCIONES)
    assert all("×" in n for n in nombres[len(FEATURES):])
    assert len(X[0]) == len(nombres)


def test_el_nivel_NO_se_juzga_por_el_Brier_global():
    """Con una tasa base de 1.8%, ganarle a la constante en Brier es casi imposible aunque el
    modelo sea bueno: el Brier premia predecir siempre la base. El criterio es el decil."""
    import inspect
    src = inspect.getsource(pq.entrenar)
    assert "curva[-1]" in src, "el nivel se juzga en el decil superior"
    assert "ERROR_DECIL_ACEPTABLE" in src
