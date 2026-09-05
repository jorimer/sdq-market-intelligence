"""Los DOS tests hermanos, que es donde se decide si el modelo es correcto.

**Por qué hacen falta los dos, y no alcanza el de identidad.** Con `ROE = Ke` el residual
income es CERO en todos los períodos, y entonces:

* un terminal calculado sobre **utilidad** en vez de sobre residual income sí se detecta —da
  un número donde debería dar cero—;
* pero un terminal **sin descontar** sigue siendo 0, porque 0 descontado o sin descontar es 0;
* y un **`BV` mal proyectado** se multiplica por cero y desaparece.

O sea que el test de identidad detecta **uno de los tres defectos posibles** y es ciego a los
otros dos. El hermano —`ROE = Ke + 1 pp` constante— los ejerce: con RI distinto de cero, un
terminal sin descontar y una trayectoria de patrimonio equivocada mueven el resultado.

Sin ambos, no hay verificación. Con uno solo, hay la ilusión de haberla hecho.
"""
import pytest

from modules.valuation.engine import excess_return as er

KE = 12.0
BV0 = 1_000_000.0


def _vp_de_una_serie(valores, ke_pct):
    ke = ke_pct / 100.0
    return sum(v / (1.0 + ke) ** (i + 1) for i, v in enumerate(valores))


# ── EL TEST DE IDENTIDAD ────────────────────────────────────────────────────────────


def test_con_ROE_igual_a_Ke_el_valor_ES_el_libro():
    """Una entidad que gana exactamente lo que su capital exige no crea ni destruye valor.

    Si esto falla, el modelo está diciendo que existe valor donde no lo hay — para TODAS las
    entidades a la vez, porque el defecto es de fórmula y no de dato.
    """
    v = er.valuar(bv_inicial=BV0, ke_pct=KE, roe_por_periodo=[KE] * 5, retencion=0.5)
    assert v.valor == pytest.approx(BV0, rel=1e-12)
    assert v.exceso_sobre_libro == pytest.approx(0.0, abs=1e-6)
    assert v.pb_implicito == pytest.approx(1.0, rel=1e-12)


def test_con_ROE_igual_a_Ke_el_terminal_tambien_es_cero():
    """El terminal es una perpetuidad de RESIDUAL INCOME. Si estuviera sobre utilidad, acá
    saldría un número grande y el valor superaría al libro."""
    v = er.valuar(bv_inicial=BV0, ke_pct=KE, roe_por_periodo=[KE] * 5, retencion=0.5)
    assert v.terminal_en_T == pytest.approx(0.0, abs=1e-9)
    assert v.terminal_descontado == pytest.approx(0.0, abs=1e-9)


# ── EL TEST HERMANO ─────────────────────────────────────────────────────────────────


def test_con_ROE_un_punto_por_encima_el_exceso_es_EXACTAMENTE_el_VP_de_la_diferencia():
    """Ejerce los dos defectos que la identidad no ve: el descuento del terminal y la
    trayectoria del patrimonio.

    Con `ROE = Ke + 1 pp` y retención `b`, el patrimonio crece a `g = b × ROE` y el residual
    income de cada año es `1 % × BV_apertura`. El valor tiene que superar al libro en
    exactamente el VP de esa serie más el VP del terminal — se calcula acá a mano, aparte del
    motor, para que no sea el mismo cálculo comparándose consigo mismo.
    """
    roe = KE + 1.0
    b = 0.5
    T = 5
    g = b * roe                       # en %
    # Trayectoria del patrimonio de apertura, a mano.
    bvs, bv = [], BV0
    for _ in range(T):
        bvs.append(bv)
        bv *= (1.0 + g / 100.0)
    ri = [0.01 * x for x in bvs]      # (ROE − Ke) = 1 pp
    vp_explicito = _vp_de_una_serie(ri, KE)
    # Terminal: RI del año T+1 sobre el patrimonio de apertura de T+1 (= `bv`), en
    # perpetuidad, descontado por (1+Ke)^T.
    ri_terminal = 0.01 * bv
    terminal = ri_terminal / ((KE - g) / 100.0)
    vp_terminal = terminal / (1.0 + KE / 100.0) ** T

    v = er.valuar(bv_inicial=BV0, ke_pct=KE, roe_por_periodo=[roe] * T, retencion=b)
    assert v.exceso_sobre_libro == pytest.approx(vp_explicito + vp_terminal, rel=1e-9)
    assert v.valor == pytest.approx(BV0 + vp_explicito + vp_terminal, rel=1e-9)


def test_el_terminal_se_descuenta_por_T_y_no_por_T_mas_uno():
    """El terminal ya está expresado en valor al momento T. Un período de más lo subestima
    sistemáticamente — y como el error es proporcional, nunca se nota comparando entidades."""
    T = 4
    v = er.valuar(bv_inicial=BV0, ke_pct=KE, roe_por_periodo=[KE + 2.0] * T, retencion=0.4)
    esperado = v.terminal_en_T / (1.0 + KE / 100.0) ** T
    assert v.terminal_descontado == pytest.approx(esperado, rel=1e-12)


# ── convergencia ────────────────────────────────────────────────────────────────────


def test_g_mayor_o_igual_a_Ke_LANZA_antes_de_calcular():
    """Verificar después es tarde: la perpetuidad ya devolvió un número que parece resultado."""
    with pytest.raises(er.HorizonteInvalidoError, match="no converge"):
        er.valuar(bv_inicial=BV0, ke_pct=10.0, roe_por_periodo=[25.0] * 5, retencion=0.9)


def test_el_caso_limite_g_igual_a_Ke_tambien_lanza():
    """Estricto: con `g == Ke` el denominador es cero."""
    with pytest.raises(er.HorizonteInvalidoError):
        er.valuar(bv_inicial=BV0, ke_pct=12.0, roe_por_periodo=[24.0] * 3, retencion=0.5,
                  g_terminal_pct=12.0)


# ── ROE sobre apertura ──────────────────────────────────────────────────────────────


def test_el_ROE_se_calcula_sobre_patrimonio_de_APERTURA():
    assert er.roe_sobre_apertura(120.0, 1000.0) == pytest.approx(12.0)


def test_la_base_promedio_da_un_ROE_MENOR_cuando_el_patrimonio_crece():
    """Por qué no se pueden mezclar: el error es sistemático, no aleatorio, y crece con el
    crecimiento de la entidad."""
    apertura, cierre, utilidad = 1000.0, 1200.0, 120.0
    sobre_apertura = er.roe_sobre_apertura(utilidad, apertura)
    sobre_promedio = utilidad / ((apertura + cierre) / 2) * 100.0
    assert sobre_apertura > sobre_promedio
    assert sobre_apertura - sobre_promedio > 1.0


def test_el_publicado_es_CONTROL_y_devuelve_la_diferencia():
    assert er.control_contra_el_publicado(12.0, 10.9) == pytest.approx(1.1)
    assert er.control_contra_el_publicado(12.0, None) is None


# ── clean surplus ───────────────────────────────────────────────────────────────────


def test_la_diferencia_de_clean_surplus_se_REPORTA_y_no_se_absorbe():
    """El balance de la SIB trae revaluaciones que no pasan por resultados. Absorber la
    diferencia dentro del valor la haría desaparecer donde nadie la puede auditar."""
    T = 3
    b = 0.5
    roe = 14.0
    # Patrimonio observado que se aparta CADA AÑO de la proyección de clean surplus.
    # Ojo: el motor re-basa sobre el observado, así que un margen fijo aplicado sobre una
    # cadena "pura" solo aparecería el primer año — el desvío tiene que componerse sobre lo
    # observado, que es como se comporta un balance con revaluaciones recurrentes.
    proyectado, obs = [], BV0
    for _ in range(T):
        obs = obs * (1.0 + b * roe / 100.0) * 1.02   # 2 % por encima, año a año
        proyectado.append(obs)
    v = er.valuar(bv_inicial=BV0, ke_pct=KE, roe_por_periodo=[roe] * T, retencion=b,
                  patrimonio_observado=proyectado)
    assert v.ajuste_clean_surplus_total != 0.0
    assert any("Clean surplus" in a for a in v.advertencias)
    assert all(p.ajuste_clean_surplus != 0.0 for p in v.periodos), (
        "el ajuste tiene que viajar POR PERÍODO: uno que se compensa entre años no es lo "
        "mismo que uno que se acumula, y agregarlo borra la distinción")


def test_sin_patrimonio_observado_no_se_inventa_un_ajuste():
    v = er.valuar(bv_inicial=BV0, ke_pct=KE, roe_por_periodo=[14.0] * 3, retencion=0.5)
    assert v.ajuste_clean_surplus_total == 0.0
    assert not v.advertencias


# ── el P/B es DERIVADO ──────────────────────────────────────────────────────────────


def test_el_pb_sale_del_valor_y_no_al_reves():
    v = er.valuar(bv_inicial=BV0, ke_pct=KE, roe_por_periodo=[KE + 3.0] * 5, retencion=0.4)
    assert v.pb_implicito == pytest.approx(v.valor / BV0, rel=1e-12)
    assert v.pb_implicito > 1.0, "con ROE por encima de Ke el P/B tiene que superar 1"
