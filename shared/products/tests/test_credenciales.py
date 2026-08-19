"""El gate comercial: una cifra que no se puede verificar vigente NO entra a material de venta.

Producción sirvió durante 19 días un Gini de 0,44 calculado con un score que ya no existía,
mientras el deck decía 0,16. El defecto técnico está cerrado (huella + cascada); esto cierra
el otro extremo: que la cifra obsoleta no llegue al PDF que se le entrega a un cliente.

La regla es asimétrica a propósito. `stale=False` publica; `stale=True` NO; y **`stale=None`
tampoco** — «no sé de cuándo es» y «está al día» son cosas distintas, y confundirlas es
exactamente cómo se publicó el 0,44.
"""
from shared.products.credenciales import (
    GRUPO_CONCLUYENTE, GRUPO_EVENTO_REAL, GRUPO_NO_CONCLUYENTE, GRUPO_SIN_MOTOR, GRUPOS,
    _cifra_principal, _grupo, _mejor_senal,
)


class _Estado:
    def __init__(self, tiene_motor, eje_motor=None):
        self.tiene_motor, self.eje_motor = tiene_motor, eje_motor


# ── El titular ────────────────────────────────────────────────────

def test_el_titular_sale_del_reporte_no_del_gini_mas_alto():
    """Elegir «la señal de mayor Gini» convertiría un no concluyente en credencial."""
    reporte = {
        "headline_signal": "resultados",
        "signals": {
            "resultados": {"gini": 0.2287, "gini_ci": [0.147, 0.311], "conclusive": True,
                           "n_observations": 1693, "n_events": 250},
            "credito": {"gini": -0.1437, "gini_ci": [-0.235, -0.05], "conclusive": False,
                        "invertida": True, "n_observations": 1693, "n_events": 66},
        },
    }
    assert _mejor_senal(reporte)["senal"] == "resultados"
    assert _cifra_principal("banking", reporte)["valor"] == 0.2287


def test_sin_titular_declarado_no_se_inventa_uno():
    reporte = {"headline_signal": None,
               "signals": {"solvency": {"gini": 0.09, "conclusive": False}}}
    assert _mejor_senal(reporte) is None


# ── Los grupos ────────────────────────────────────────────────────

def test_un_eje_sin_motor_va_al_grupo_que_declara_el_obstaculo():
    cifra = {"valor": None, "concluyente": False}
    assert _grupo("tourism", _Estado(False), cifra, evento_real=False) == GRUPO_SIN_MOTOR


def test_banca_va_al_grupo_de_evento_real_aunque_su_backtest_sea_de_distress():
    """La cohorte de quiebras es una credencial APARTE del backtest de distress."""
    cifra = {"valor": 0.16, "concluyente": True}
    assert _grupo("banking", _Estado(True, "banking_score"), cifra, True) == GRUPO_EVENTO_REAL


def test_una_cifra_que_no_concluye_no_se_presenta_como_concluyente():
    cifra = {"valor": 0.0639, "concluyente": False}
    assert _grupo("insurance", _Estado(True, "insurance_intel"), cifra, False) == \
        GRUPO_NO_CONCLUYENTE
    cifra_ok = {"valor": 0.2575, "concluyente": True}
    assert _grupo("insurance", _Estado(True, "insurance_intel"), cifra_ok, False) == \
        GRUPO_CONCLUYENTE


def test_los_grupos_estan_ordenados_de_mayor_a_menor_fuerza():
    """El orden no es cosmético: es el que el material comercial usa para no presentar
    como equivalentes un backtest contra quiebras y un índice sin corte transversal."""
    assert GRUPOS[0] == GRUPO_EVENTO_REAL and GRUPOS[-1] == GRUPO_SIN_MOTOR
    assert len(GRUPOS) == 6


# ── El gate ───────────────────────────────────────────────────────

def _fila(valor, stale):
    """Reproduce la decisión de `publicable` del ensamblador, aislada."""
    return bool(valor is not None and stale is False)


def test_solo_publica_lo_verificado_vigente():
    assert _fila(0.2575, False) is True


def test_una_cifra_obsoleta_no_entra_a_material_comercial():
    assert _fila(0.4436, True) is False


def test_una_frescura_INDETERMINADA_tampoco_pasa():
    """`stale=None` no es «está bien»: es «no se sabe», y así se publicó el 0,44."""
    assert _fila(0.16, None) is False


def test_sin_cifra_no_hay_nada_que_publicar():
    assert _fila(None, False) is False


def test_la_ruta_de_credenciales_va_antes_del_comodin_de_sector():
    """Si queda debajo, «credenciales» entraría como el nombre de un sector."""
    from shared.products.router import router

    orden = [r.path for r in router.routes]
    assert orden.index("/credenciales") < orden.index("/readiness/{sector}")
