"""La regla de proyección va en el NÚCLEO del Cerebro, no por eje.

Que una cifra sea la salida de un modelo y no un hecho observado no es una particularidad de
macro: es una regla de la casa. Si viviera en `AXIS_DOCTRINE[axis]`, el primer eje nuevo que
emita proyecciones nacería sin ella y nadie se enteraría — que es el modo en que esta
plataforma pierde reglas.
"""
from shared.narrative.cerebro import AXIS_DOCTRINE, EPISTEMIC_STANDARD


def test_el_estandar_habla_de_proyeccion():
    assert "PROYECCIÓN" in EPISTEMIC_STANDARD


def test_exige_nombrarla_siempre_como_proyeccion():
    e = EPISTEMIC_STANDARD.lower()
    assert "nómbrala siempre como proyección" in e or "nombrala siempre como proyección" in e


def test_prohibe_compararla_con_un_dato_observado_sin_decirlo():
    e = EPISTEMIC_STANDARD.lower()
    assert "nunca la compares" in e and "observado" in e


def test_exige_decirlo_en_la_primera_linea_si_la_lectura_descansa_ahi():
    assert "primera línea" in EPISTEMIC_STANDARD.lower()


def test_no_se_coló_en_la_doctrina_de_un_eje():
    """Si estuviera por eje, un eje nuevo nacería sin la regla."""
    colados = [k for k, v in AXIS_DOCTRINE.items() if "PROYECCIÓN:" in v]
    assert not colados, f"la regla del núcleo se duplicó en los ejes {colados}"
