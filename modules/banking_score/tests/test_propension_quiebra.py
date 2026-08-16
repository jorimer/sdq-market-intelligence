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


# ── La explicación: que no invente mecanismos ──

def _mod_con_perfil(perfil, coef):
    n = tuple(FEATURES) + tuple(f"{a}×{b}" for a, b, _ in pq.INTERACCIONES)
    return pq.ModeloPropension(
        features=n, coef=coef, intercepto=-4.0,
        media=tuple(0.0 for _ in n), escala=tuple(1.0 for _ in n),
        tasa_base=0.018, n_periodos=1400, n_eventos=26, n_entidades=38,
        auc=0.75, auc_ic95=(0.66, 0.84), brier=0.018, brier_constante=0.0179,
        perfil_univariado=perfil, ordena=True, nivel_confiable=True)


def test_una_variable_sin_mecanismo_declarado_es_CONTROL_y_no_se_narra():
    """La cobertura de provisiones: AUC univariado 0.44 —las que quebraron tenían MEJOR
    cobertura— y quitarla baja el modelo de 0.750 a 0.713. Es útil y no explica. Narrarla
    producía "tener las provisiones completas eleva la propensión a quebrar"."""
    perfil = {f: (1.0, 0.0, 0.70) for f in FEATURES}
    perfil["brecha_provisiones"] = (22.5, 24.6, 0.441)
    coef = {f: 0.3 for f in FEATURES} | {f"{a}×{b}": 0.0 for a, b, _ in pq.INTERACCIONES}
    coef["brecha_provisiones"] = -0.52
    m = _mod_con_perfil(perfil, coef)
    assert pq._rol(m, "brecha_provisiones") == "control"
    e = pq.explicar(m, {f: 1.0 for f in FEATURES})
    narrados = [t["nombre"] for t in e["empujan_al_alza"] + e["empujan_a_la_baja"]]
    assert "brecha_provisiones" not in narrados
    assert e["controles_no_narrables"]


def test_el_crecimiento_se_narra_con_el_mecanismo_del_DATO_no_el_de_la_literatura():
    """Los bancos dominicanos que quebraron se CONTRAÍAN (−6.5% contra +18.5%). El mecanismo
    declarado es −1 justamente por eso: la literatura de 2003 dice lo contrario y el dato
    manda. Imponer el signo 'de manual' sería forzar un prior que la evidencia contradice."""
    assert pq.MECANISMO_ESPERADO["crecimiento_anomalo"] == -1
    perfil = {f: (1.0, 0.0, 0.70) for f in FEATURES}
    perfil["crecimiento_anomalo"] = (-0.065, 0.185, 0.304)
    coef = {f: 0.3 for f in FEATURES} | {f"{a}×{b}": 0.0 for a, b, _ in pq.INTERACCIONES}
    coef["crecimiento_anomalo"] = -0.72
    m = _mod_con_perfil(perfil, coef)
    assert pq._rol(m, "crecimiento_anomalo") == "impulsor"


def test_la_descomposicion_es_exacta():
    """La suma de las contribuciones más el intercepto reconstruye la propensión sin residuo.
    No es una heurística de atribución: es la identidad de la regresión logística."""
    perfil = {f: (1.0, 0.0, 0.70) for f in FEATURES}
    coef = {f: 0.3 for f in FEATURES} | {f"{a}×{b}": 0.1 for a, b, _ in pq.INTERACCIONES}
    m = _mod_con_perfil(perfil, coef)
    ind = {f: 0.5 for f in FEATURES}
    assert abs(pq.explicar(m, ind)["propension"] - pq.evaluar(m, ind)["propension"]) < 1e-9


def test_la_cifra_sale_con_su_unidad_no_transformada():
    """`morosidad_nivel` es "mora menos el piso de su tipo": publicar el −4.04 pelado no dice
    nada. Es el mismo defecto que ya apareció en la §Alerta Temprana."""
    assert "puntos" in pq._expresar("morosidad_nivel", -4.04)
    assert "%" in pq._expresar("crecimiento_anomalo", 0.707)
    # y la unidad NO se repite en las referencias
    assert "puntos" not in pq._expresar("morosidad_nivel", 15.6, con_unidad=False)
