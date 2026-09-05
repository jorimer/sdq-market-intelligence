"""El segundo motor: qué tiene que ser cierto para que aporte una segunda opinión.

**Existe para CONTRASTAR, no para promediar.** El Excess Return dice cuánto vale la entidad
según lo que gana sobre su costo de capital; la regresión dice a cuánto cotizan bancos con
fundamentales parecidos. Dos preguntas, dos fuentes de error. Cuando divergen, **la
divergencia es información**: el mercado comparable paga algo que el flujo no explica, o al
revés. Promediarlos hasta que parezca una sola respuesta borra exactamente eso — y produce un
número que ninguno de los dos modelos sostiene.

**El gate del panel no es prudencia, es aritmética.** Cinco predictores y veinte bancos dan un
`R²` alto porque el modelo memoriza, no porque explique. Un segundo motor mal estimado no da
una segunda opinión: da una coincidencia inventada, que es peor que no tener el segundo motor.

**Y el error fuera de muestra manda sobre el `R²`.** El `R²` describe el panel; lo que importa
es qué pasa con un banco que el modelo no vio.
"""
import math

import pytest

from modules.valuation.engine import pb_regression as pbr
from modules.valuation.panel import latam_comparables as panel_mod
from modules.valuation.panel.latam_comparables import Comparable, estado


def _banco(i: int, *, roe=15.0, ruido=0.0) -> Comparable:
    """Un comparable sintético cuyo P/B es una función CONOCIDA de sus fundamentales."""
    crec = 5.0 + (i % 5)
    vol = 1.0 + (i % 3) * 0.5
    logact = 15.0 + (i % 7) * 0.2
    cal = 92.0 + (i % 4)
    pb = 0.20 + 0.070 * roe - 0.030 * vol + 0.010 * crec + ruido
    return Comparable(ticker=f"BK{i}", pais="XX", pb=pb, roe_pct=roe, crecimiento_pct=crec,
                      volatilidad_roe=vol, log_activos=logact, calidad_cartera_pct=cal,
                      fuente="sintético", capturado_el="2026-09-05")


def _panel(n: int, ruido=0.0, semilla=7):
    """Panel sintético. El ruido va de un generador SEMBRADO y no de `i`.

    Primer intento: el ruido era `f(i % 7)` — y `log_activos` también. O sea perfectamente
    colineal con un predictor, así que la regresión lo absorbía entero y el ajuste salía
    exacto: no era ruido, era una quinta señal. Un "ruido" que el modelo puede explicar no
    prueba nada sobre el error fuera de muestra.
    """
    import random

    rnd = random.Random(semilla)
    return [_banco(i, roe=8.0 + (i % 13), ruido=rnd.gauss(0.0, ruido) if ruido else 0.0)
            for i in range(n)]


# ── el gate del panel ───────────────────────────────────────────────────────────────


def test_el_panel_de_hoy_esta_VACIO_y_lo_declara():
    """No es un descuido de cableado: no hay proveedor de datos de mercado conectado."""
    est = estado()
    assert est.n == 0 and not est.suficiente
    assert "no hay proveedor" in est.motivo.lower()
    assert str(est.minimo) in est.motivo


def test_el_minimo_es_DIEZ_por_predictor():
    assert panel_mod.MINIMO_DE_BANCOS == len(panel_mod.PREDICTORES) * panel_mod.POR_PREDICTOR
    assert panel_mod.MINIMO_DE_BANCOS == 50


def test_con_panel_corto_NO_estima_y_dice_por_que():
    with pytest.raises(pbr.PanelInsuficienteError, match="memoriza"):
        pbr.ajustar(_panel(20))


def test_el_gate_se_consulta_ANTES_de_regresar():
    """Estimar y después mirar el n es tarde: ya hay un R² que parece un resultado."""
    with pytest.raises(pbr.PanelInsuficienteError):
        pbr.ajustar([])


# ── la estimación ───────────────────────────────────────────────────────────────────


def test_recupera_los_coeficientes_conocidos_sin_ruido():
    """El P/B del panel sintético es una función exacta de tres predictores; la regresión
    tiene que encontrarlos. Si no, el álgebra está mal y ningún R² lo diría."""
    aj = pbr.ajustar(_panel(60))
    coef = dict(zip(aj.nombres, aj.coeficientes))
    assert coef["roe_pct"] == pytest.approx(0.070, abs=1e-6)
    assert coef["volatilidad_roe"] == pytest.approx(-0.030, abs=1e-6)
    assert coef["crecimiento_pct"] == pytest.approx(0.010, abs=1e-6)
    assert aj.r2 == pytest.approx(1.0, abs=1e-9)


def test_reporta_R2_y_error_FUERA_de_muestra():
    """El sensor de T-VL-6. El R² solo describe el panel."""
    aj = pbr.ajustar(_panel(60, ruido=0.05))
    assert 0.0 < aj.r2 <= 1.0
    assert aj.rmse_oos > 0.0
    assert aj.n == 60


def test_el_error_fuera_de_muestra_es_ESTRICTAMENTE_mayor_que_el_de_adentro():
    """La brecha entre los dos ES la medida de sobreajuste, y por eso se publican los dos.

    ESTRICTAMENTE mayor, con margen: un `>=` deja pasar la implementación que reporta el de
    adentro como si fuera el de afuera —y ésa fue exactamente la rotura que este test no
    cazaba en su primera versión—. Dejar uno afuera SIEMPRE infla el error cuando hay ruido:
    el modelo se estima sin la observación que después tiene que predecir.
    """
    aj = pbr.ajustar(_panel(60, ruido=0.05))
    assert aj.rmse_oos > aj.rmse_in, (
        "el error fuera de muestra no supera al de adentro: probablemente se está "
        "reportando el mismo número dos veces")
    assert aj.sobreajuste > 0.0
    # Con n=60 y 5 predictores, dejar-uno-afuera infla el error de forma perceptible.
    assert aj.rmse_oos / aj.rmse_in > 1.02


def test_mas_ruido_empeora_el_error_fuera_de_muestra():
    """Contraejemplo del anterior: un `rmse_oos` constante pasaría los dos tests de arriba."""
    poco = pbr.ajustar(_panel(60, ruido=0.02)).rmse_oos
    mucho = pbr.ajustar(_panel(60, ruido=0.20)).rmse_oos
    assert mucho > poco * 2


def test_predice_el_PB_de_una_entidad_nueva():
    aj = pbr.ajustar(_panel(60))
    pb = pbr.pb_predicho(aj, roe_pct=15.0, crecimiento_pct=6.0, volatilidad_roe=1.5,
                         log_activos=15.4, calidad_cartera_pct=93.0)
    esperado = 0.20 + 0.070 * 15.0 - 0.030 * 1.5 + 0.010 * 6.0
    assert pb == pytest.approx(esperado, abs=1e-6)


# ── el cruce: dos motores, un rango ─────────────────────────────────────────────────


def test_cuando_coinciden_lo_dice_y_NO_promedia():
    c = pbr.contrastar(1.20, 1.25)
    assert not c.divergen
    assert c.rango == (1.20, 1.25)
    assert "coinciden" in c.lectura


def test_cuando_divergen_la_divergencia_ES_el_resultado():
    c = pbr.contrastar(0.90, 1.60)
    assert c.divergen
    assert "hallazgo" in c.lectura
    assert "promedio" in c.lectura, "no dice explícitamente que no se promedia"


def test_la_lectura_distingue_QUIEN_paga_de_mas():
    """No alcanza con decir que divergen: cuál está por encima cambia la interpretación."""
    comparables_arriba = pbr.contrastar(0.90, 1.60)
    flujo_arriba = pbr.contrastar(1.60, 0.90)
    assert "comparables pagan más" in comparables_arriba.lectura
    assert "flujo justifica más" in flujo_arriba.lectura


def test_el_contraste_NUNCA_devuelve_un_punto_intermedio():
    """El guard del diseño: promediar produce un número que ninguno de los dos modelos
    sostiene, y encima esconde que se contradicen."""
    c = pbr.contrastar(0.90, 1.60)
    bajo, alto = c.rango
    assert bajo == 0.90 and alto == 1.60
    promedio = (0.90 + 1.60) / 2
    assert promedio not in (c.pb_excess_return, c.pb_regresion, bajo, alto)


def test_el_codigo_NO_promedia_los_dos_motores():
    """Guard estructural: si aparece un promedio entre los dos, el diseño se perdió."""
    import pathlib
    fuente = pathlib.Path(pbr.__file__).read_text()
    assert "/ 2" not in fuente.replace("rango", ""), "hay algo que parece un promedio"
    assert "no se promedia" in fuente.lower() or "NUNCA promediados" in fuente
