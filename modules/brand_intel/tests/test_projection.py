"""Tests del motor de proyección de venta.

Las propiedades que se protegen aquí no son «el número da bien». Son las que, cuando
fallan, producen un pronóstico plausible y falso: fuga temporal, ceros que entran como
venta baja, una banda simétrica inventada sobre errores absolutos, y locales impredecibles
que desaparecen del informe en vez de declararse.
"""
import math
from datetime import date, timedelta

from modules.brand_intel.engines import projection as P


# ─────────────────────────────────────────────────────────────────────────────
# Constructores de panel sintético
# ─────────────────────────────────────────────────────────────────────────────

START = date(2026, 1, 5)  # un lunes


def _panel(stores, days, value_fn):
    return [
        P.Observation(store, START + timedelta(days=i), value_fn(store, START + timedelta(days=i)))
        for store in stores
        for i in range(days)
    ]


# ─────────────────────────────────────────────────────────────────────────────
# Fuga temporal
# ─────────────────────────────────────────────────────────────────────────────

def test_el_backtest_no_ve_el_futuro():
    """Una regla solo puede usar jornadas anteriores al corte.

    Se construye una serie plana que da un salto en un día conocido. Si el backtest
    filtrara mal, las reglas 'sabrían' del salto antes de que ocurra y su error sería
    absurdamente bajo. Con filtrado correcto, el salto las sorprende a todas.
    """
    jump_day = START + timedelta(days=50)

    def value(store, day):
        return 1000.0 if day < jump_day else 5000.0

    result = P.project(_panel(["A", "B"], 70, value), horizon=7)
    assert result is not None
    # Fuera del salto la serie es perfectamente predecible, así que una implementación
    # con fuga daría error prácticamente nulo. Que el error sea materialmente distinto de
    # cero es la prueba de que el salto llegó sin aviso.
    assert result.overall_mape is not None and result.overall_mape > 0.05
    assert result.band_hi_pct is not None and result.band_hi_pct > 50.0


def test_last_same_dow_solo_mira_hacia_atras():
    train = {"A": {START + timedelta(days=i): float(i) for i in range(14)}}
    predict = P._build_last_same_dow(train)
    target = START + timedelta(days=21)
    # El mismo día de semana más reciente ANTES del objetivo es el día 14 (índice 13...
    # el lunes más cercano dentro del entrenamiento).
    got = predict("A", target)
    assert got is not None
    assert got == train["A"][max(d for d in train["A"] if d.weekday() == target.weekday())]


# ─────────────────────────────────────────────────────────────────────────────
# El cero no es una venta baja
# ─────────────────────────────────────────────────────────────────────────────

def test_las_jornadas_en_cero_quedan_fuera():
    """El tablero emite el mes completo: lo posterior al corte viene en cero.

    Si esas jornadas entraran, hundirían el nivel de cada local sin que nada falle.
    """
    obs = _panel(["A"], 40, lambda s, d: 1000.0)
    obs += [P.Observation("A", START + timedelta(days=40 + i), 0.0) for i in range(20)]
    usable = P._usable(obs)
    assert len(usable) == 40
    assert all(o.value > 0 for o in usable)


def test_sin_datos_utilizables_declina_en_vez_de_inventar():
    assert P.project([P.Observation("A", START, 0.0)], horizon=7) is None
    assert P.project([], horizon=7) is None


# ─────────────────────────────────────────────────────────────────────────────
# La banda sale de desviaciones CON SIGNO
# ─────────────────────────────────────────────────────────────────────────────

def test_la_banda_es_asimetrica_cuando_el_error_lo_es():
    """Con un modelo que se queda corto casi siempre, el borde superior debe ser mayor
    en magnitud que el inferior. Una banda armada sobre errores absolutos y aplicada
    simétricamente inventaría un borde que el backtest nunca midió.
    """
    def value(store, day):
        # Nivel estable con saltos hacia ARRIBA periódicos: el error es asimétrico.
        return 1000.0 * (1.6 if day.day % 5 == 0 else 1.0)

    result = P.project(_panel(["A", "B", "C"], 70, value), horizon=7)
    assert result is not None
    assert result.band_lo_pct is not None and result.band_hi_pct is not None
    assert result.band_lo_pct < result.band_hi_pct
    assert abs(result.band_hi_pct) > abs(result.band_lo_pct)


def test_la_banda_del_punto_usa_los_dos_bordes():
    """Con ruido real los dos bordes difieren, porque salen de percentiles distintos.

    Sobre una serie perfectamente determinista la banda colapsa a cero, y eso también es
    correcto: un modelo que no erró nunca fuera de muestra no tiene por qué abrir banda.
    """
    import random
    rng = random.Random(11)

    def value(store, day):
        base = 1000.0 * (1.5 if day.weekday() >= 5 else 1.0)
        return base * math.exp(rng.gauss(0.0, 0.12))

    result = P.project(_panel(["A", "B"], 70, value), horizon=7)
    assert result is not None and result.points
    for point in result.points:
        assert point.lo <= point.point <= point.hi
        # Los bordes no son el punto ± el mismo número: salen de percentiles distintos.
        assert not math.isclose(point.point - point.lo, point.hi - point.point, rel_tol=1e-6)


def test_el_sesgo_se_declara():
    """Un pronóstico que corre corto lo dice; no se esconde detrás de la banda."""
    def value(store, day):
        i = (day - START).days
        return 1000.0 * (1.0 + 0.02 * i)  # serie creciente: las reglas se quedan cortas

    result = P.project(_panel(["A", "B"], 70, value), horizon=14)
    assert result is not None
    assert result.share_above_pct is not None and result.share_above_pct > 55.0
    assert result.bias_pct is not None and result.bias_pct > 0
    assert "sesgado" in result.basis


# ─────────────────────────────────────────────────────────────────────────────
# Forma común, escala por local
# ─────────────────────────────────────────────────────────────────────────────

def _con_dispersiones(sigmas, days=70, seed=3):
    import random
    rng = random.Random(seed)
    obs = []
    for store, sigma in sigmas.items():
        for i in range(days):
            day = START + timedelta(days=i)
            base = 1000.0 * (1.5 if day.weekday() >= 5 else 1.0)
            obs.append(P.Observation(store, day, base * math.exp(rng.gauss(0.0, sigma))))
    return obs


def test_cada_local_recibe_su_propia_banda():
    """Una banda única para toda la red miente por local: sobra en el estable y falta en
    el volátil. Sobre el panel real cubría 80% en promedio y entre 29% y 100% por local."""
    result = P.project(_con_dispersiones({"QUIETO": 0.04, "MEDIO": 0.12, "RUIDOSO": 0.30}),
                       horizon=7)
    assert result is not None
    ancho = {
        v.store_id: v.band_hi_pct - v.band_lo_pct
        for v in result.verdicts
        if v.band_hi_pct is not None and v.band_lo_pct is not None
    }
    assert ancho["QUIETO"] < ancho["MEDIO"] < ancho["RUIDOSO"]
    # Y la diferencia es material, no decorativa.
    assert ancho["RUIDOSO"] > 2.0 * ancho["QUIETO"]


def test_la_escala_se_encoge_hacia_la_comun():
    """El encogimiento acerca la escala propia a la de la red sin borrar la diferencia."""
    per_store = {"A": [0.01] * 5 + [-0.01] * 5, "B": [0.5] * 5 + [-0.5] * 5}
    sin_encoger, pooled = P._shrunk_scales(per_store, k=0.0)
    encogidas, _ = P._shrunk_scales(per_store, k=100.0)
    assert sin_encoger["A"] < encogidas["A"] < pooled or math.isclose(encogidas["A"], pooled,
                                                                     rel_tol=0.2)
    assert encogidas["B"] < sin_encoger["B"]      # el volátil se modera
    assert encogidas["A"] > sin_encoger["A"]      # el quieto se ensancha
    assert encogidas["A"] < encogidas["B"]        # pero el orden se conserva


def test_la_forma_se_toma_de_la_red_estandarizada():
    """Los cuantiles de forma salen de residuos estandarizados: no arrastran escala ajena."""
    per_store = {"A": [-2.0, -1.0, 0.0, 1.0, 2.0], "B": [-20.0, -10.0, 0.0, 10.0, 20.0]}
    scales = {"A": 1.0, "B": 10.0}
    q_lo, q_hi = P._shape_quantiles(per_store, scales)
    assert q_lo is not None and q_hi is not None
    # Estandarizados, ambos locales aportan la MISMA forma: los cuantiles son simétricos.
    assert math.isclose(q_lo, -q_hi, rel_tol=1e-9)


def test_la_banda_publicada_cubre_lo_que_promete():
    """Control de construcción: si la cobertura sobre sus propios residuos no da cerca del
    nominal, hay un error de implementación, no un hallazgo."""
    result = P.project(_con_dispersiones({"A": 0.05, "B": 0.15, "C": 0.25}), horizon=7)
    assert result is not None and result.calibration is not None
    cov = result.calibration.coverage_pct
    assert cov is not None
    assert abs(cov - result.calibration.nominal_coverage_pct) < 6.0


def test_la_glosa_de_forma_se_computa_y_no_se_afirma():
    """La frase debe seguir a la cifra medida. Incrustarla es lo que deja al informe
    contradiciendo su propio número cuando el diagnóstico cambia."""
    pesada = P._shape_note(0.0, 4.1)
    liviana = P._shape_note(-0.17, 0.23)
    assert "cola pesada" in pesada
    assert "cola pesada" not in liviana
    assert "normal" in liviana
    assert P._shape_note(None, None) != pesada


# ─────────────────────────────────────────────────────────────────────────────
# El error se mide contra el REAL
# ─────────────────────────────────────────────────────────────────────────────

def test_el_denominador_del_error_es_el_valor_real():
    """``|real − pronóstico| / real``. Con el pronóstico en el denominador, un modelo
    que subestima sistemáticamente saldría premiado."""
    # real = 100, pronóstico = 80  ->  |100-80|/100 = 0.20
    d = math.log(100.0) - math.log(80.0)
    assert math.isclose(P._mape([d]), 0.20, rel_tol=1e-9)
    # real = 80, pronóstico = 100  ->  |80-100|/80 = 0.25
    d2 = math.log(80.0) - math.log(100.0)
    assert math.isclose(P._mape([d2]), 0.25, rel_tol=1e-9)


# ─────────────────────────────────────────────────────────────────────────────
# Veredicto por local
# ─────────────────────────────────────────────────────────────────────────────

def test_el_local_sin_historia_se_declara_no_proyectable():
    obs = _panel(["LARGO"], 70, lambda s, d: 1000.0 * (1.4 if d.weekday() >= 5 else 1.0))
    obs += _panel(["CORTO"], 10, lambda s, d: 1000.0)
    result = P.project(obs, horizon=7)
    assert result is not None
    corto = next(v for v in result.verdicts if v.store_id == "CORTO")
    assert not corto.projectable
    assert corto.reason == P.REASON_SHORT_HISTORY


def test_el_local_que_no_le_gana_a_su_promedio_se_declara():
    """Puro ruido sin patrón: ninguna regla debe superar al promedio del propio local.

    Lo importante no es que falle, es que **aparezca declarado**. Ocultarlo lo haría
    desaparecer sin aviso y el informe afirmaría una cobertura que no tiene.
    """
    import random
    rng = random.Random(7)
    ruido = [
        P.Observation("RUIDO", START + timedelta(days=i), 1000.0 * math.exp(rng.gauss(0, 0.5)))
        for i in range(70)
    ]
    senal = _panel(["SENAL"], 70, lambda s, d: 1000.0 * (1.5 if d.weekday() >= 5 else 1.0))
    result = P.project(ruido + senal, horizon=7)
    assert result is not None
    verdicts = {v.store_id: v for v in result.verdicts}
    assert verdicts["SENAL"].projectable
    assert verdicts["RUIDO"].reason in (P.REASON_NO_LIFT, None)
    # Y en todo caso el error del local ruidoso queda registrado, no ausente.
    assert verdicts["RUIDO"].mape is not None


def test_solo_se_proyectan_los_locales_proyectables():
    obs = _panel(["LARGO"], 70, lambda s, d: 1000.0 * (1.4 if d.weekday() >= 5 else 1.0))
    obs += _panel(["CORTO"], 10, lambda s, d: 1000.0)
    result = P.project(obs, horizon=7)
    assert result is not None
    proyectados = {p.store_id for p in result.points}
    assert "CORTO" not in proyectados
    assert "LARGO" in proyectados


# ─────────────────────────────────────────────────────────────────────────────
# La celda con valor límite no cae al respaldo
# ─────────────────────────────────────────────────────────────────────────────

def test_una_celda_de_valor_uno_no_cae_al_respaldo():
    """``log(1) == 0.0``, que es falso en Python. Una celda estimada en cero es un
    resultado legítimo y no debe confundirse con «no hay celda»."""
    train = {"A": {START: 0.0, START + timedelta(days=7): 0.0,
                   START + timedelta(days=1): 5.0}}
    predict = P._build_store_dow(train)
    assert predict("A", START + timedelta(days=14)) == 0.0  # lunes: la celda, no el promedio


# ─────────────────────────────────────────────────────────────────────────────
# Descomposición de la varianza
# ─────────────────────────────────────────────────────────────────────────────

def test_la_varianza_separa_escala_de_local_de_dia_nacional():
    """Panel donde todo el movimiento diario es común a la red: el día nacional debe
    llevarse la variación que no es escala, y el residuo debe quedar en casi nada."""
    def value(store, day):
        nivel = {"A": 1000.0, "B": 3000.0, "C": 500.0}[store]
        comun = 1.0 + 0.3 * math.sin((day - START).days)
        return nivel * comun

    shares = P.variance_decomposition(_panel(["A", "B", "C"], 70, value))
    assert shares is not None
    assert shares.store_pct > 80.0
    assert shares.residual_pct < 1.0
    assert shares.national_day_pct > shares.residual_pct


def test_la_varianza_detecta_patron_propio_de_cada_local():
    """Cada local con su propio pico semanal, sin nada en común: el día nacional no
    puede explicarlo y el residuo debe conservar la estructura."""
    picos = {"A": 0, "B": 3, "C": 6}

    def value(store, day):
        return 1000.0 * (2.0 if day.weekday() == picos[store] else 1.0)

    shares = P.variance_decomposition(_panel(["A", "B", "C"], 70, value))
    assert shares is not None
    assert shares.residual_pct > shares.national_day_pct
    assert shares.acf_lag7 is not None and shares.acf_lag7 > 0.5


def test_la_varianza_declina_con_historia_corta():
    assert P.variance_decomposition(_panel(["A"], 5, lambda s, d: 1000.0)) is None


# ─────────────────────────────────────────────────────────────────────────────
# Tráfico, cheque y la venta derivada
# ─────────────────────────────────────────────────────────────────────────────

class _Row:
    def __init__(self, store_id, business_date, sales, transactions):
        self.store_id = store_id
        self.business_date = business_date
        self.sales = sales
        self.transactions = transactions


def _rows(stores, days=70, seed=5):
    import random
    rng = random.Random(seed)
    out = []
    for store, (tx_base, check_base, sigma) in stores.items():
        for i in range(days):
            day = START + timedelta(days=i)
            fin_de_semana = 1.4 if day.weekday() >= 5 else 1.0
            tx = tx_base * fin_de_semana * math.exp(rng.gauss(0.0, sigma))
            check = check_base * math.exp(rng.gauss(0.0, sigma / 3.0))
            out.append(_Row(store, day, tx * check, int(round(tx))))
    return out


def test_el_cheque_se_computa_no_se_lee():
    rows = [_Row("A", START, 1000.0, 50)]
    traffic, check = P.split_traffic_and_check(rows)
    assert traffic[0].value == 50.0
    assert math.isclose(check[0].value, 20.0)


def test_una_jornada_sin_transacciones_no_entra_en_ninguna_serie():
    """No entra a tráfico con cero ni a cheque con un valor imputado: no entra."""
    rows = [
        _Row("A", START, 1000.0, 50),
        _Row("A", START + timedelta(days=1), 1000.0, None),
        _Row("A", START + timedelta(days=2), None, 50),
        _Row("A", START + timedelta(days=3), 1000.0, 0),
    ]
    traffic, check = P.split_traffic_and_check(rows)
    assert len(traffic) == 1 and len(check) == 1


def test_la_sobredispersion_se_mide_y_distingue_poisson():
    """Un conteo invita por reflejo a Poisson. El Fano dice si hace falta."""
    import random
    rng = random.Random(2)

    poisson = [
        P.Observation("A", START + timedelta(days=i), float(_poisson(rng, 400.0)))
        for i in range(70)
    ] + [
        P.Observation("B", START + timedelta(days=i), float(_poisson(rng, 400.0)))
        for i in range(70)
    ]
    disperso = [
        P.Observation(s, o.day, o.value * math.exp(rng.gauss(0.0, 0.12)))
        for s in ("A", "B")
        for o in poisson if o.store_id == s
    ]

    d_poisson = P.overdispersion(poisson)
    d_disperso = P.overdispersion(disperso)
    assert d_poisson is not None and d_disperso is not None
    assert d_poisson.fano_median < 3.0
    assert d_disperso.fano_median > 3.0 * d_poisson.fano_median
    assert "no justifica un modelo de conteo aparte" in d_disperso.note
    assert "no justifica un modelo de conteo aparte" not in d_poisson.note


def _poisson(rng, mean):
    """Poisson por el método de Knuth. Evita traer una dependencia al test."""
    limit = math.exp(-mean) if mean < 700 else 0.0
    if limit == 0.0:  # media alta: aproximación normal, suficiente para el Fano
        return max(0, int(round(rng.gauss(mean, math.sqrt(mean)))))
    k, p = 0, 1.0
    while p > limit:
        k += 1
        p *= rng.random()
    return k - 1


def test_la_venta_derivada_cuadra_exacto_con_sus_componentes():
    """Publicar las tres por separado deja al informe afirmando que tráfico por cheque no
    da la venta. Derivarla lo vuelve imposible."""
    result = P.decompose(_rows({"A": (900, 300.0, 0.10), "B": (500, 260.0, 0.18)}), horizon=7)
    assert result is not None
    traffic = {(p.store_id, p.day): p.point for p in result.traffic.points}
    check = {(p.store_id, p.day): p.point for p in result.check.points}
    assert result.sales_points
    for point in result.sales_points:
        key = (point.store_id, point.day)
        assert math.isclose(point.point, traffic[key] * check[key], rel_tol=1e-12)


def test_la_banda_de_la_venta_supera_a_la_de_cada_componente():
    """Componer la banda de las escalas ya encogidas las encoge dos veces y sobre el panel
    real dejaba seis locales con la venta más angosta que su propio tráfico, que es
    imposible. La banda de un producto se mide sobre el producto."""
    result = P.decompose(_rows({"A": (900, 300.0, 0.10), "B": (500, 260.0, 0.22)}), horizon=7)
    assert result is not None
    def ancho(v):
        return v.band_hi_pct - v.band_lo_pct

    traffic = {v.store_id: ancho(v) for v in result.traffic.verdicts if v.band_lo_pct is not None}
    check = {v.store_id: ancho(v) for v in result.check.verdicts if v.band_lo_pct is not None}
    sales = {
        p.store_id: (p.hi / p.point - p.lo / p.point) * 100.0
        for p in result.sales_points if p.point > 0
    }
    assert sales
    for store_id, width in sales.items():
        assert width >= traffic.get(store_id, 0.0) - 1e-6
        assert width >= check.get(store_id, 0.0) - 1e-6


def test_la_incertidumbre_de_la_venta_se_reparte_entre_trafico_y_cheque():
    """Con el cheque tres veces más estable que el tráfico, el tráfico manda."""
    result = P.decompose(_rows({"A": (900, 300.0, 0.12), "B": (500, 260.0, 0.12)}), horizon=7)
    assert result is not None
    assert result.traffic_share_pct is not None
    assert result.traffic_share_pct > 60.0
    assert result.residual_correlation is not None


def test_la_descomposicion_declina_sin_transacciones():
    rows = [_Row("A", START + timedelta(days=i), 1000.0, None) for i in range(70)]
    assert P.decompose(rows, horizon=7) is None


# ─────────────────────────────────────────────────────────────────────────────
# La vara existe y compite
# ─────────────────────────────────────────────────────────────────────────────

def test_la_vara_esta_entre_las_reglas_puntuadas():
    result = P.project(
        _panel(["A", "B"], 70, lambda s, d: 1000.0 * (1.4 if d.weekday() >= 5 else 1.0)),
        horizon=7,
    )
    assert result is not None
    assert P.BASELINE_RULE in {r.rule for r in result.ranked_rules}
    assert result.baseline_mape is not None


def test_con_patron_semanal_la_regla_ganadora_le_gana_a_la_vara():
    result = P.project(
        _panel(["A", "B", "C"], 70, lambda s, d: 1000.0 * (1.6 if d.weekday() >= 5 else 1.0)),
        horizon=7,
    )
    assert result is not None
    assert result.overall_mape is not None and result.baseline_mape is not None
    assert result.overall_mape < result.baseline_mape
    assert result.rule != P.BASELINE_RULE


# ─────────────────────────────────────────────────────────────────────────────
# La sección del informe
# ─────────────────────────────────────────────────────────────────────────────

def test_la_seccion_declara_los_locales_excluidos():
    """El defecto que esto ataca no falla: publica una sección impecable sobre la parte
    buena del panel. Un local sin pronóstico que no se nombra desaparece sin aviso, y el
    documento afirma una cobertura que no tiene."""
    from modules.brand_intel import report_docs

    pr = {
        "available": True,
        "horizonte_dias": 14,
        "pct_incertidumbre_venta_que_aporta_el_trafico": 84,
        "error_medio_trafico_pct": 7.41,
        "error_de_la_vara_trafico_pct": 12.94,
        "error_medio_cheque_pct": 3.62,
        "locales_proyectables": 28,
        "locales_en_el_panel": 30,
        "locales_no_proyectables": [
            {"label": "Santiago Center", "motivo": P.REASON_NO_LIFT, "jornadas": 70},
            {"label": "Recién Abierto", "motivo": P.REASON_SHORT_HISTORY, "jornadas": 9},
        ],
        "pct_jornadas_en_que_el_real_supero_al_pronostico": 62.0,
        "nota_motor": "nota del motor",
    }
    texto = report_docs._fallback_projection(pr)
    assert "28 de 30" in texto
    assert "Santiago Center" in texto and "Recién Abierto" in texto
    # El motivo se traduce: el término del motor es vocabulario interno y en un documento
    # de cliente no dice lo que significa.
    assert P.REASON_NO_LIFT not in texto and P.REASON_SHORT_HISTORY not in texto
    assert report_docs._PROJECTION_REASON[P.REASON_NO_LIFT] in texto
    assert report_docs._PROJECTION_REASON[P.REASON_SHORT_HISTORY] in texto


def test_ninguna_cadena_servida_afirma_la_forma_del_residuo():
    """La forma la describe SOLO `Calibration.note`, computada de la curtosis medida.

    El defecto: `basis` decía «porque el residuo tiene cola pesada» y viajaba al modelo
    junto a una nota que —tras estandarizar por local— dice que se aproxima a una normal.
    Dos cadenas contradiciéndose en el mismo contexto. Ya lo había cerrado `_shape_note`
    en su cadena; arreglarlo en un solo lugar no es arreglarlo.
    """
    import random
    rng = random.Random(4)

    def value(store, day):
        base = 1000.0 * (1.5 if day.weekday() >= 5 else 1.0)
        return base * math.exp(rng.gauss(0.0, 0.10))

    result = P.project(_panel(["A", "B", "C"], 70, value), horizon=14)
    assert result is not None and result.calibration is not None
    assert "cola pesada" not in result.basis
    assert "normal" not in result.basis
    # Y la nota de forma sí la describe, siguiendo a la cifra.
    assert str(round(result.calibration.excess_kurtosis, 1)) in result.calibration.note


def test_ninguna_cadena_servida_cita_el_identificador_de_la_regla():
    """El informe de producción salió citando «regla store_dow_drift_14» a la Dirección.

    Nombrar la regla ganadora es disciplina de la casa y está bien; nombrarla es decir qué
    hace, no citar la variable del motor. Mismo defecto que los motivos sin traducir.
    """
    result = P.project(
        _con_dispersiones({"A": 0.08, "B": 0.14, "C": 0.20}), horizon=14)
    assert result is not None
    for rule_id in P.RULES:
        assert rule_id not in result.basis
    assert P.rule_label(result.rule) in result.basis


def test_las_cifras_servidas_llevan_la_notacion_del_documento():
    """El informe de producción salió con «1,260 predicciones», en notación inglesa.

    El motor servía `1260` sin separador y el modelo lo formateó por su cuenta. Un número
    entregado sin formato es un número que el modelo va a formatear.
    """
    # Hace falta pasar del millar para que el separador exista: 30 locales × 70 jornadas.
    sigmas = {f"L{i:02d}": 0.06 + 0.005 * i for i in range(30)}
    result = P.project(_con_dispersiones(sigmas), horizon=7)
    assert result is not None
    n = next(r.n_predictions for r in result.ranked_rules if r.rule == result.rule)
    assert n >= 1000, "el panel del test tiene que superar el millar para probar esto"
    assert f"{n:,}" not in result.basis          # notación inglesa: fuera
    assert f"{n:,}".replace(",", ".") in result.basis


def test_toda_regla_del_motor_tiene_nombre_legible():
    """Una regla nueva sin etiqueta vuelve a filtrar su identificador al documento."""
    assert set(P.RULES) <= set(P.RULE_LABELS)
    assert all(v and not v.startswith("store_") for v in P.RULE_LABELS.values())


def test_todo_motivo_del_motor_tiene_traduccion():
    """Un motivo nuevo en el motor sin su traducción sale al PDF como «motivo no
    declarado», que es peor que el término técnico: borra la información."""
    from modules.brand_intel import report_docs

    del_motor = {P.REASON_NO_LIFT, P.REASON_SHORT_HISTORY, P.REASON_NO_SCORED}
    assert del_motor <= set(report_docs._PROJECTION_REASON)


def test_la_seccion_declara_el_sesgo_cuando_lo_hay():
    from modules.brand_intel import report_docs

    base = {"available": True, "horizonte_dias": 14, "locales_proyectables": 30,
            "locales_en_el_panel": 30}
    sesgado = report_docs._fallback_projection(
        {**base, "pct_jornadas_en_que_el_real_supero_al_pronostico": 62.0})
    calibrado = report_docs._fallback_projection(
        {**base, "pct_jornadas_en_que_el_real_supero_al_pronostico": 50.4})
    assert "sesgado" in sesgado
    assert "sesgado" not in calibrado


def test_la_plantilla_exige_banda_por_local_y_cobertura():
    """La prosa que el modelo debe respetar vive en la CONSTANTE, no en un dict armado al
    vuelo: un literal partido por ancho de línea deja de existir en el fuente."""
    from shared.narrative.claude_engine import THIN_TEMPLATES

    tpl = THIN_TEMPLATES["brand_sales_projection"]
    assert "locales_no_proyectables_con_motivo" in tpl
    assert "REGLA DURA DE BANDA" in tpl
    assert "REGLA DURA DE COBERTURA" in tpl
    assert "REGLA DURA DE SESGO" in tpl
    # Y el pronóstico jamás se presenta como lo que va a pasar.
    assert "PROHIBIDO" in tpl


def test_el_contexto_de_ia_sirve_los_excluidos_no_solo_los_buenos():
    from modules.brand_intel import report as rpt

    payload = {
        "engagement": {"focal_brand": "M", "market": "RD", "category": "QSR",
                       "provider": "Prov", "client": "C", "slug": "s"},
        "waves": [], "frame": {},
        "sections": {
            "projection": {
                "available": True, "horizonte_dias": 14,
                "locales": [{"label": "A", "error_medio_pct": 4.3}],
                "locales_no_proyectables": [{"label": "B", "motivo": P.REASON_NO_LIFT}],
            },
        },
    }
    ctx = rpt.cerebro_contexts(payload)["projection"]
    assert ctx["locales_no_proyectables_con_motivo"][0]["label"] == "B"
    assert ctx["locales_con_su_error_y_banda"][0]["label"] == "A"
