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
    from shared.products.credenciales import GRUPO_EMPATA_TAMANO

    assert GRUPOS[0] == GRUPO_EVENTO_REAL and GRUPOS[-1] == GRUPO_SIN_MOTOR
    assert len(GRUPOS) == len(set(GRUPOS)), "hay un grupo repetido"
    # El del EMPATE va inmediatamente después del concluyente y antes de todo lo demás: es
    # más débil que «discrimina» y más fuerte que «no dejó afirmación», y ponerlo en
    # cualquiera de los dos extremos publica una afirmación falsa o prohíbe una verdadera.
    assert GRUPOS.index(GRUPO_EMPATA_TAMANO) == GRUPOS.index(GRUPO_CONCLUYENTE) + 1


def test_todo_grupo_esta_documentado_en_el_material_de_VENTA():
    """Un grupo que existe en el código y no en `docs/CLAIMS_COMERCIALES.md` es un rótulo que
    nadie sabe qué autoriza a decir — y el documento es lo que lee quien arma una propuesta.

    Es la regla de «un tipo NUEVO se registra en TODAS sus superficies»: al anuario le
    faltaron cuatro registros de a uno y ninguno falló, cada uno lo hacía desaparecer en un
    lugar distinto.
    """
    import pathlib

    raiz = pathlib.Path(__file__).resolve().parents[3]
    doc = (raiz / "docs" / "CLAIMS_COMERCIALES.md").read_text(encoding="utf-8")
    faltan = [g for g in GRUPOS if g.split(" ·")[0] + " ·" not in doc]
    assert not faltan, (
        f"grupos sin documentar en CLAIMS_COMERCIALES.md: {faltan}. El documento dice qué "
        "autoriza a decir cada uno; sin la fila, el grupo no significa nada para quien vende")


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


# ── El veredicto contra el tamaño, en la tabla comercial ──────────
#
# Medido en producción el 2026-09-01: de las CINCO filas del grupo B —el que autoriza a decir
# «discrimina contra un desenlace realizado»— TRES empataban con el tamaño del sujeto: macro
# (0,199), ESG (−0,509) y seguros/underwriting (0,258). La tabla traía el control como un
# blob crudo, sin veredicto, y el grupo no lo consultaba. Quien armara una propuesta con esa
# tabla afirmaría una ventaja que la propia plataforma computa como inexistente.

_CONTROL_PLANO = {           # irmp, comercio, ESG, seguros, pensiones
    "gini": 0.2404, "veredicto": "empate: el tamaño solo alcanza…",
    "empata_con_el_score": True, "el_tamano_alcanza_al_score": True,
}
_CONTROL_ANIDADO = {         # sector_intel, que mide DOS desenlaces
    "intensidad": {"mean_yearly_ic": -0.323, "veredicto": "empate: el tamaño solo alcanza…",
                   "empata_con_el_score": True, "el_tamano_alcanza_al_score": True},
    "nivel": {"mean_yearly_ic": 0.377, "veredicto": "empate: …",
              "empata_con_el_score": True, "el_tamano_alcanza_al_score": True},
}


def test_el_veredicto_se_extrae_de_las_DOS_formas_del_control():
    """Un extractor por forma es cómo una se queda atrás: los motores publican su control
    plano o anidado por desenlace, y las dos tienen que llegar a la tabla."""
    from shared.products.credenciales import _veredicto_del_control

    for blob in (_CONTROL_PLANO, _CONTROL_ANIDADO):
        v = _veredicto_del_control(blob)
        assert v["empata_con_el_tamano"] is True
        assert v["control_medido"] is True
        assert v["veredicto_contra_el_tamano"].startswith("empate")


def test_del_control_ANIDADO_se_toma_el_desenlace_que_produce_la_cifra():
    """`intensidad` es el desenlace primario de ese motor, o sea el que produce la cifra que
    la tabla publica. Emparejar la cifra de un desenlace con el control de OTRO sería peor
    que no traer control: diría que se comparó cuando no."""
    from shared.products.credenciales import _veredicto_del_control

    anidado = {"intensidad": {"mean_yearly_ic": -0.323, "veredicto": "empate: intensidad",
                              "empata_con_el_score": True},
               "nivel": {"mean_yearly_ic": 0.377, "veredicto": "empate: nivel",
                         "empata_con_el_score": False}}
    assert _veredicto_del_control(anidado)["veredicto_contra_el_tamano"] == "empate: intensidad"


def test_SIN_control_el_veredicto_dice_no_evaluable_y_no_calla():
    """«No sé si el tamaño lo explica» y «el tamaño no lo explica» son cosas distintas. Es el
    mismo defecto del `stale=null` que originó este módulo."""
    from shared.validation.control_tamano import VEREDICTO_CONTROL_NO_EVALUABLE
    from shared.products.credenciales import _veredicto_del_control

    for vacio in (None, {}, {"gini": 0.2}, {"intensidad": {"mean_yearly_ic": 0.1}}):
        v = _veredicto_del_control(vacio)
        assert v["veredicto_contra_el_tamano"] == VEREDICTO_CONTROL_NO_EVALUABLE
        assert v["control_medido"] is False
        assert v["empata_con_el_tamano"] is False


def test_una_cifra_que_concluye_pero_EMPATA_no_se_sienta_en_el_grupo_concluyente():
    """El corazón de la fase. La afirmación «discrimina contra un desenlace realizado» sigue
    siendo cierta; la que NO se puede sostener es la de VENTAJA sobre el tamaño."""
    from shared.products.credenciales import GRUPO_EMPATA_TAMANO

    empata = {"valor": 0.2575, "concluyente": True, "empata_con_el_tamano": True}
    gana = {"valor": 0.2320, "concluyente": True, "empata_con_el_tamano": False}
    estado = _Estado(True, "insurance_intel")
    assert _grupo("insurance", estado, empata, False) == GRUPO_EMPATA_TAMANO
    assert _grupo("trade", estado, gana, False) == GRUPO_CONCLUYENTE


def test_un_empate_que_NO_concluye_sigue_yendo_al_grupo_sin_credencial():
    """El contra-caso: el empate solo reclasifica lo que YA concluía. Sin conclusión, la fila
    pertenece al grupo que dice que no dejó afirmación vendible, no a uno más suave."""
    cifra = {"valor": -0.274, "concluyente": False, "empata_con_el_tamano": True}
    assert _grupo("agribusiness", _Estado(True, "sector_intel"), cifra, False) == \
        GRUPO_NO_CONCLUYENTE


def test_TODA_cifra_de_la_tabla_trae_su_veredicto_aunque_no_haya_control():
    """El barrido, con su prueba negativa: `_cifra_principal` tiene siete caminos de retorno
    —cada motor eligió su forma antes de que hubiera contrato— y uno que se olvide devuelve
    una cifra sin calificador, que es justo lo que esta fase existe para impedir."""
    import ast
    import inspect

    from shared.products import credenciales as mod

    fn = next(n for n in ast.walk(ast.parse(inspect.getsource(mod)))
              if isinstance(n, ast.FunctionDef) and n.name == "_cifra_principal")
    retornos = [n for n in ast.walk(fn) if isinstance(n, ast.Return)
                and isinstance(n.value, ast.Dict)]
    assert len(retornos) >= 5, "el barrido no encontró los caminos de retorno"
    sin_veredicto = [
        i for i, r in enumerate(retornos)
        if not any(isinstance(k, ast.Constant) and k.value == "control_de_tamano"
                   for k in r.value.keys if k is not None)
        or not any(isinstance(n, ast.Call) and isinstance(n.func, ast.Name)
                   and n.func.id == "_veredicto_del_control" for n in ast.walk(r))
    ]
    assert not sin_veredicto, (
        f"{len(sin_veredicto)} de {len(retornos)} caminos devuelven una cifra sin su veredicto "
        "contra el tamaño")
