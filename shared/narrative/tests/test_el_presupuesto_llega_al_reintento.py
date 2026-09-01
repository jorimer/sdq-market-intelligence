"""El techo de ensamblado tiene que ser VISIBLE desde el motor, o el guard lo hace estallar.

**El caso.** El techo (`PRESUPUESTO_DE_ENSAMBLADO_S = 270`) vivía solo en el ensamblador. El
motor, que no lo conocía, podía arrancar una regeneración del guard a los 250 s. Y el corte no
pierde esa sección: **descarta el ensamblado entero**, incluidas las secciones ya terminadas, y
el reintento del usuario arranca de cero y vuelve a pagarlo todo.

El intercambio que este módulo elige, dicho de frente: **una sección posiblemente mejorada por
un informe entregado.** Y bajo la regla vigente de dos capas, la marca que sobrevive casi
siempre se publica igual — en la ventana medida, las diez marcas registradas eran del detector
mecánico y ninguna bloqueó la entrega.
"""
import time

import pytest

from shared.narrative.presupuesto import MARGEN, cabe, con_presupuesto, queda


# ── El presupuesto en sí ──────────────────────────────────────────

def test_sin_presupuesto_declarado_NO_bloquea_nada():
    """Tests, scripts y trabajos de fondo se comportan igual que antes. Invertir este
    default convertiría un módulo de observación en un estrangulador."""
    assert queda() is None
    assert cabe(9999.0) is True


def test_lo_que_no_entra_en_lo_que_queda_no_se_intenta():
    with con_presupuesto(10):
        assert cabe(1.0) is True
        assert cabe(20.0) is False


def test_el_MARGEN_es_lo_que_hace_util_la_decision():
    """Terminar EXACTO en el vencimiento no sirve de nada: el ensamblado se corta igual.

    El caso decisivo es el que cabría SIN margen y no cabe CON él: con 10 s de presupuesto,
    un trabajo de 9 s entra por los pelos (`9,99 > 9`) y termina prácticamente en el
    vencimiento. La primera versión de este test comparaba contra el costo exacto y pasaba
    aunque el margen no existiera —quedaban 9,999 s y 9,999 > 10 ya era falso—, o sea que
    daba verde sobre el código sin margen. Comprobado por mutación.
    """
    with con_presupuesto(10):
        assert cabe(9.0) is False, "sin margen esto entraría y terminaría en el vencimiento"
        assert cabe(10.0 / MARGEN * 0.9) is True


def test_sin_estimacion_tampoco_se_bloquea():
    """No saber cuánto cuesta no es saber que no cabe. Negar por defecto convertiría cada
    hueco de instrumentación en una degradación silenciosa del informe."""
    with con_presupuesto(1):
        assert cabe(None) is True
        assert cabe(0) is True


def test_anidar_solo_puede_ACHICAR_el_presupuesto():
    """Un presupuesto interno no puede extender el del ensamblado que lo contiene: el que
    corta es el de afuera, y creerse el de adentro es cómo se vuelve al mismo corte."""
    with con_presupuesto(100):
        with con_presupuesto(5):
            assert queda() < 6
        with con_presupuesto(1000):
            assert queda() < 101, "un presupuesto anidado extendió el de afuera"


def test_al_salir_se_restaura_el_de_afuera():
    with con_presupuesto(100):
        with con_presupuesto(5):
            pass
        assert 90 < (queda() or 0) <= 100


def test_un_presupuesto_VENCIDO_devuelve_negativo_en_vez_de_cero():
    """«Se pasó por 12 s» y «llegó justo» son cosas distintas, y quien lo registre necesita
    distinguirlas."""
    with con_presupuesto(0.01):
        time.sleep(0.05)
        assert (queda() or 0) < 0
        assert cabe(0.001) is False


def test_no_se_usa_un_CENTINELA_numerico_para_ausencia():
    """`time.monotonic()` no tiene origen fijo: un 0.0 como «sin presupuesto» ata la lógica
    al uptime del proceso —en uno recién arrancado 0.0 es «ahora»— y ese defecto ya se pagó
    en este repo."""
    import ast
    import inspect

    from shared.narrative import presupuesto as mod

    arbol = ast.parse(inspect.getsource(mod))
    default = next(kw.value for n in ast.walk(arbol)
                   if isinstance(n, ast.Call) and getattr(n.func, "attr", "") == "ContextVar"
                   for kw in n.keywords if kw.arg == "default")
    assert isinstance(default, ast.Constant) and default.value is None


# ── El motor se abstiene, y lo REGISTRA ───────────────────────────

class _MotorFalso:
    """Genera texto que el guard marca siempre, y tarda `demora` en cada llamada."""

    def __init__(self, demora):
        self.demora = demora
        self.llamadas = 0

    def __call__(self, *_a, **_k):
        self.llamadas += 1
        time.sleep(self.demora)
        return "texto"


def _correr_bucle(demora, presupuesto, max_reintentos=2):
    """Reproduce la DECISIÓN del bucle del motor, aislada de la red.

    No se reimplementa el guard: lo que se prueba es la regla de abstención —cuántas veces se
    regenera— con la misma llamada a `cabe()` y la misma re-estimación por intento que el
    motor. Un test contra el motor entero necesitaría cliente, y probaría la red.
    """
    motor = _MotorFalso(demora)
    with con_presupuesto(presupuesto):
        t0 = time.monotonic()
        motor()
        costo = time.monotonic() - t0
        sin_reintento = False
        for _intento in range(1, max_reintentos + 1):
            if not cabe(costo):
                sin_reintento = True
                break
            t0 = time.monotonic()
            motor()
            costo = time.monotonic() - t0
    return motor.llamadas, sin_reintento


def test_con_holgura_el_guard_regenera_las_dos_veces():
    """El contra-caso, sin el cual «no regenerar nunca» pasaría los otros tests."""
    llamadas, sin_reintento = _correr_bucle(demora=0.01, presupuesto=30)
    assert llamadas == 3, "generación + dos regeneraciones"
    assert sin_reintento is False


def test_sin_holgura_NO_arranca_una_regeneracion_que_va_a_morir():
    llamadas, sin_reintento = _correr_bucle(demora=0.05, presupuesto=0.06)
    assert llamadas == 1, "regeneró con el presupuesto casi agotado"
    assert sin_reintento is True


def test_se_abstiene_A_MITAD_de_camino_si_el_margen_se_agota():
    """Cada intento re-estima con SU propio costo: el segundo puede tardar más que el
    primero, y arrastrar la medición del primero subestimaría justo cuando queda menos."""
    llamadas, sin_reintento = _correr_bucle(demora=0.05, presupuesto=0.14)
    assert llamadas == 2, f"esperaba generación + una regeneración, hubo {llamadas}"
    assert sin_reintento is True


# ── Que el motor lo lea, y que quede registrado ───────────────────

def test_el_MOTOR_consulta_el_presupuesto_antes_de_regenerar():
    """Guard estructural: los tests de arriba prueban la REGLA; éste, que el motor la use.
    Sin esto, la regla podría vivir perfecta y nadie llamarla."""
    import ast
    import inspect

    from shared.narrative import claude_engine as mod

    fuente = inspect.getsource(mod)
    assert "from shared.narrative.presupuesto import cabe, queda" in fuente
    arbol = ast.parse(fuente)
    bucles = [n for n in ast.walk(arbol)
              if isinstance(n, ast.For)
              and any(isinstance(c, ast.Call) and getattr(c.func, "id", "") == "cabe"
                      for c in ast.walk(n))]
    assert bucles, "ningún bucle del motor consulta `cabe()` antes de regenerar"


def test_la_abstencion_queda_REGISTRADA_y_no_se_confunde_con_un_guard_peor():
    """«Reintentó y la marca sobrevivió» y «no llegó a reintentar por tiempo» se ven idénticas
    en el resultado. Sin la bandera, apagar reintentos se leería en la telemetría como una
    degradación de la calidad del guard."""
    import inspect

    from shared.narrative import claude_engine as mod

    assert "guard_sin_reintento_por_tiempo" in inspect.getsource(mod)
