"""El gate comercial: una cifra que no se puede verificar vigente NO entra a material de venta.

Producción sirvió durante 19 días un Gini de 0,44 calculado con un score que ya no existía,
mientras el deck decía 0,16. El defecto técnico está cerrado (huella + cascada); esto cierra
el otro extremo: que la cifra obsoleta no llegue al PDF que se le entrega a un cliente.

La regla es asimétrica a propósito. `stale=False` publica; `stale=True` NO; y **`stale=None`
tampoco** — «no sé de cuándo es» y «está al día» son cosas distintas, y confundirlas es
exactamente cómo se publicó el 0,44.
"""
from shared.products.credenciales import (
    GRUPO_CONCLUYENTE, GRUPO_EMPATA_TAMANO, GRUPO_EVENTO_REAL, GRUPO_NO_CONCLUYENTE,
    GRUPO_SIN_MOTOR, GRUPOS, _cifra_principal, _grupo, _mejor_senal,
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
    assert _grupo("tourism", _Estado(False), cifra) == GRUPO_SIN_MOTOR


def test_el_grupo_de_la_fila_sale_de_LA_CIFRA_que_la_fila_publica():
    """Banca entraba al grupo de evento real POR SER BANCA, sin mirar el número.

    Quedaba una fila con el RÓTULO de una medición —la cohorte de quiebras— y la CIFRA de
    otra —el backtest de distress—. Se vio cuando el control de tamaño llegó a la tabla: el
    rótulo decía «validado contra evento real» sobre un Gini de 0,2489 que el activo total
    supera con 0,5553. La credencial de evento real no se pierde: viaja como bloque propio,
    con sus números (ver `test_la_credencial_de_evento_real_viaja_aparte`).
    """
    sin_ventaja = {"valor": 0.2489, "concluyente": True, "el_tamano_alcanza": True}
    assert _grupo("banking", _Estado(True, "banking_score"), sin_ventaja) == \
        GRUPO_EMPATA_TAMANO


def test_una_cifra_que_no_concluye_no_se_presenta_como_concluyente():
    cifra = {"valor": 0.0639, "concluyente": False}
    assert _grupo("insurance", _Estado(True, "insurance_intel"), cifra) == \
        GRUPO_NO_CONCLUYENTE
    cifra_ok = {"valor": 0.2575, "concluyente": True}
    assert _grupo("insurance", _Estado(True, "insurance_intel"), cifra_ok) == \
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
    assert _grupo("insurance", estado, empata) == GRUPO_EMPATA_TAMANO
    assert _grupo("trade", estado, gana) == GRUPO_CONCLUYENTE


def test_un_empate_que_NO_concluye_sigue_yendo_al_grupo_sin_credencial():
    """El contra-caso: el empate solo reclasifica lo que YA concluía. Sin conclusión, la fila
    pertenece al grupo que dice que no dejó afirmación vendible, no a uno más suave."""
    cifra = {"valor": -0.274, "concluyente": False, "empata_con_el_tamano": True}
    assert _grupo("agribusiness", _Estado(True, "sector_intel"), cifra) == \
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


# ── El control DECLARADO que no llega a la fila ────────────────────

def test_una_senal_sin_control_no_dice_que_el_tamano_no_explica():
    """El defecto real, en el eje insignia. Banca publicaba su control en la RAÍZ del
    reporte —acotando el desenlace agregado— y la credencial publica la señal TITULAR, que
    es otro desenlace. La fila salía con `control_medido: false` sentada en el grupo que
    autoriza a decir «discrimina», y nada lo decía."""
    reporte = {
        "headline_signal": "resultados",
        "control_solo_tamano": {"gini": 0.413, "veredicto": "x",
                                "el_tamano_alcanza_al_score": True},
        "signals": {"resultados": {"gini": 0.2512, "gini_ci": [0.17, 0.33],
                                   "conclusive": True, "n_observations": 1693,
                                   "n_events": 250}},
    }
    cifra = _cifra_principal("banking", reporte)
    assert cifra["control_medido"] is False
    assert cifra["empata_con_el_tamano"] is False
    assert "no evaluable" in cifra["veredicto_contra_el_tamano"]


def test_el_control_dentro_de_la_senal_SI_llega_a_la_fila():
    """La cura: viaja pegado al Gini que acota, como en seguros, pensiones y comercio."""
    reporte = {
        "headline_signal": "resultados",
        "signals": {"resultados": {
            "gini": 0.2512, "gini_ci": [0.17, 0.33], "conclusive": True,
            "n_observations": 1693, "n_events": 250,
            "control_solo_tamano": {"gini": 0.2100, "veredicto": "el score ordena mejor",
                                    "el_tamano_alcanza_al_score": False,
                                    "empata_con_el_score": True},
        }},
    }
    cifra = _cifra_principal("banking", reporte)
    assert cifra["control_medido"] is True
    assert cifra["empata_con_el_tamano"] is True
    assert cifra["control_de_tamano"]["gini"] == 0.21


def test_la_plataforma_REPORTA_el_control_declarado_que_no_llego():
    """No alcanza con arreglarlo una vez: si vuelve a pasar en otro motor, la plataforma lo
    dice. Un eje que declara control en el registro y sale sin él en la fila es una
    CONTRADICCIÓN, no una ausencia de dato — y no tenía dónde verse."""
    from shared.products.credenciales import control_declarado_que_no_llego

    filas = [
        {"eje": "banking", "valor": 0.25, "control_declarado": True, "control_medido": False},
        {"eje": "trade", "valor": 0.30, "control_declarado": True, "control_medido": True},
        # Declara control pero todavía no tiene cifra: no es el defecto que se busca.
        {"eje": "esg", "valor": None, "control_declarado": True, "control_medido": False},
        # No declara control: su ausencia está explicada en el registro.
        {"eje": "tourism", "valor": 0.1, "control_declarado": False, "control_medido": False},
    ]
    assert control_declarado_que_no_llego(filas) == ["banking"]


def test_si_el_tamano_GANA_la_fila_tampoco_puede_afirmar_ventaja():
    """El hueco que dejaba pasar el resultado más grave.

    El grupo miraba solo el EMPATE. Cuando el control no empata sino que SUPERA al score
    —el caso peor— la fila se quedaba en el grupo que autoriza a decir «discrimina» a secas.
    Le pasó a banca el 2026-09-01, apenas su control llegó a la tabla: el activo total ordena
    el mismo desenlace con 0,5553 contra 0,2489 del score, con los intervalos sin tocarse.
    """
    gana_el_tamano = {"valor": 0.2489, "concluyente": True,
                      "empata_con_el_tamano": False, "el_tamano_alcanza": True}
    assert _grupo("x", _Estado(True, "m"), gana_el_tamano) == GRUPO_EMPATA_TAMANO


def test_con_ventaja_real_la_fila_SI_se_queda_en_el_grupo_de_arriba():
    """La regla no puede degradar a todo el mundo: sin eso, el test de arriba pasaría con un
    `_grupo` que devolviera B2 siempre."""
    con_ventaja = {"valor": 0.30, "concluyente": True,
                   "empata_con_el_tamano": False, "el_tamano_alcanza": False}
    assert _grupo("trade", _Estado(True, "trade_intel"), con_ventaja) == \
        GRUPO_CONCLUYENTE


# ── La credencial de EVENTO REAL viaja aparte ──────────────────────

def test_la_credencial_de_evento_real_viaja_aparte(monkeypatch):
    """Es otra medición, con otra evidencia. Deja de ser un rótulo sobre la cifra de otro.

    Lo que la tabla no puede publicar es «6 de 6»: `found=True` significa «hay serie
    histórica», no «la alerta se encendió». La afirmación que la cohorte sostiene es el LEAD
    TIME y su N — medido el 2026-09-01: 3 de 6, con 11, 7 y **0** meses.
    """
    from modules.banking_score.products import BankingProduct

    prod = BankingProduct(db=object())
    monkeypatch.setattr(
        "modules.banking_score.historical_service.cohort_backtest",
        lambda _db: {
            "cohort": [{"nombre": n, "found": True} for n in
                       ("BNC", "Mercantil", "Baninter", "Global", "Universal", "Panamericano")],
            "n_found": 6,
            "leads": {"BNC": 11, "Mercantil": 0, "Baninter": 7,
                      "Global": None, "Universal": None, "Panamericano": None},
        })
    c = prod.credencial_evento_real()
    assert c["n_cohorte"] == 6 and c["n_con_serie"] == 6
    # LA CIFRA QUE SE CITA. Si esto fuera 6, la tabla afirmaría una detección que no ocurrió.
    assert c["n_con_lead_medido"] == 3
    assert c["lead_mediano_meses"] == 7
    # El peor caso viaja al lado del mediano: una de las tres no anticipó nada.
    assert c["lead_minimo_meses"] == 0
    assert "no es «detectada»" in c["advertencia"]


def test_sin_base_no_se_inventa_una_credencial_de_evento_real():
    from modules.banking_score.products import BankingProduct

    assert BankingProduct(db=None).credencial_evento_real() is None


def test_una_credencial_que_falla_no_tumba_la_tabla():
    """La leen todas las superficies comerciales: un eje roto no puede llevarse el resto."""
    from shared.products.credenciales import _safe_evento_real

    class _Rota:
        def credencial_evento_real(self):
            raise RuntimeError("la cohorte no se pudo computar")

    assert _safe_evento_real(_Rota()) is None
    assert _safe_evento_real(object()) is None      # un producto sin la credencial


def test_el_grupo_de_evento_real_se_puebla_DESDE_el_bloque():
    """Ninguna fila se sienta en A por su cifra —A es una credencial paralela—, así que si
    `por_grupo` mirara solo el grupo de la fila, el grupo más fuerte del catálogo quedaría
    vacío y se leería como que nadie tiene validación contra evento real."""
    from shared.products.credenciales import GRUPO_EVENTO_REAL as A

    filas = [
        {"eje": "banking", "grupo": GRUPO_EMPATA_TAMANO,
         "credencial_evento_real": {"n_con_lead_medido": 3}},
        {"eje": "trade", "grupo": GRUPO_CONCLUYENTE, "credencial_evento_real": None},
    ]
    por_grupo = {
        g: ([f["eje"] for f in filas if f.get("credencial_evento_real")] if g == A
            else [f["eje"] for f in filas if f["grupo"] == g])
        for g in GRUPOS
    }
    assert por_grupo[A] == ["banking"]
    assert por_grupo[GRUPO_EMPATA_TAMANO] == ["banking"]
    assert por_grupo[GRUPO_CONCLUYENTE] == ["trade"]
