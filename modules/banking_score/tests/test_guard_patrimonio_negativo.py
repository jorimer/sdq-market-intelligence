"""Una entidad INSOLVENTE no puede sacar el mejor puntaje del indicador prudencial.

**El caso real, encontrado en producción el 2026-08-20.** Placidoiv (agente de cambio) publica
`capitalizacion` con crudo **−1.459,14** —patrimonio negativo— y `apalancamiento` con crudo
−1,0685 y score **100 sobre 100**. De ahí salía `solidez = 50` (el promedio de 0 y 100) y un
`overall` de 26,25 en vez de un score de fondo.

La causa: `pasivos / patrimonio` con patrimonio negativo da un número negativo, y como la
escala del apalancamiento es invertida (menos es mejor), el clamp lo manda al techo. El peor
estado posible entraba por la puerta del mejor.

El motor de bancos ya lo había resuelto en `d4c3806` (2026-06-22), cuando el mismo defecto
producía un swing de 30 puntos en BPD. Los dos submodelos escritos después no lo copiaron.
"""
from types import SimpleNamespace

from modules.banking_score.scoring import cambiaria, fiduciaria


def _dato(**campos):
    base = dict(patrimonio_tecnico=None, activos_totales=None, pasivos_exigibles=None,
                utilidad_neta=None, activos_liquidos=None, cartera_bruta=None)
    base.update(campos)
    return SimpleNamespace(**base)


# ── El caso de Placidoiv, con sus cifras ──────────────────────────

def test_el_apalancamiento_de_una_cambiaria_insolvente_ya_no_saca_cien():
    """Reproduce el crudo publicado: −1,0685 sacaba 100."""
    d = _dato(patrimonio_tecnico=-1000.0, pasivos_exigibles=1068.5, activos_totales=100.0)
    res = cambiaria._apalancamiento(d)
    assert res["raw"] < 0
    assert res["score"] == 0.0, "Patrimonio negativo es el PEOR estado prudencial, no el mejor."
    assert res["available"] is True, (
        "Disponible a propósito: declararlo N/D renormalizaría la dimensión y borraría la "
        "insolvencia del score en vez de hundirlo."
    )


def test_la_solidez_de_una_cambiaria_insolvente_deja_de_ser_cincuenta():
    """Era el promedio de 0 (capitalización) y 100 (apalancamiento). Ahora es 0."""
    d = _dato(patrimonio_tecnico=-1000.0, pasivos_exigibles=1068.5, activos_totales=100.0)
    indicadores = cambiaria.calculate_cambiaria_indicators(d)
    subs = cambiaria.calculate_cambiaria_sub_components(indicadores)
    assert subs["solidez"] == 0.0


def test_el_roe_con_patrimonio_negativo_se_declara_en_vez_de_mentir():
    """Una pérdida sobre patrimonio negativo da un ROE POSITIVO: no es el peor valor, miente."""
    d = _dato(patrimonio_tecnico=-1000.0, utilidad_neta=-50.0, activos_totales=100.0)
    res = cambiaria._roe(d)
    assert res["raw"] > 0, "El signo se da vuelta — ese es el punto del guard."
    assert res["available"] is False


# ── El espejo: el mismo defecto estaba en fiduciarias ─────────────

def test_la_fiduciaria_tiene_la_misma_cura_que_su_gemelo():
    d = _dato(patrimonio_tecnico=-1000.0, pasivos_exigibles=720.0, activos_totales=100.0)
    assert fiduciaria._apalancamiento(d)["score"] == 0.0
    assert fiduciaria._roe(_dato(patrimonio_tecnico=-1000.0, utilidad_neta=-50.0,
                                 activos_totales=100.0))["available"] is False


# ── Y una entidad sana no cambia ──────────────────────────────────

def test_una_entidad_con_patrimonio_POSITIVO_puntua_igual_que_antes():
    """El guard no puede mover a nadie que no esté insolvente."""
    sana = _dato(patrimonio_tecnico=1000.0, pasivos_exigibles=0.0, activos_totales=1100.0,
                 utilidad_neta=100.0)
    assert cambiaria._apalancamiento(sana)["score"] == 100.0  # sin pasivos: el mejor, de verdad
    assert cambiaria._roe(sana).get("available") is not False  # sin la clave = disponible
    assert fiduciaria._apalancamiento(sana)["score"] == 100.0
