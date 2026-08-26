"""La inversión de dirección también se dice con VERBO, y por ahí salió publicada.

Caso real (Deep Dive de banca múltiple, 2026-03-31, §7 «Análisis Comparativo»):

    «La capitalización contable (7.41% de activos) SUPERA en 3.70 puntos porcentuales al
     promedio de su grupo.»

El contexto servía «por debajo del promedio de bancos múltiples en 3.70 puntos porcentuales»,
y la §2 y la §10 del MISMO documento lo decían bien (7.41% contra una mediana de grupo de
11.11%, verificada contra el panel de prod). O sea: el modelo copió la magnitud y redactó la
palabra al revés — exactamente el modo de falla que `derived._lectura` documenta.

El guard tenía el dato y no lo vio, por DOS huecos independientes:

  1. `supera` y `excede` ya estaban en `_MAYOR` —el vocabulario del detector hermano— y
     nunca se copiaron al patrón de brecha. Un guard existe en un motor y falta en el otro,
     dentro del mismo archivo.
  2. El patrón exigía el marcador DESPUÉS de la unidad ("3.70 puntos POR DEBAJO"); la forma
     verbo-primero no la contemplaba ninguno.

Y un tercero, de pareo: el modelo PARAFRASEÓ la etiqueta ("su grupo" por "bancos múltiples"),
así que el pareo por texto tampoco la encontraba. Se resuelve por magnitud ÚNICA, que sigue
siendo decidible; con dos comparaciones de la misma magnitud, el guard se calla.
"""
import pytest

from shared.narrative.derived import comparaciones_vs_referencia
from shared.narrative.numeric_guard import deterministic_direction_gap_errors

#: Contexto real del caso: patrimonio/activos del sujeto contra su grupo y contra el sistema.
_CTX = {"comparaciones": comparaciones_vs_referencia(
    {"patrimonio_activos": 7.4058},
    {"patrimonio_activos": {"promedio de bancos múltiples": 11.11,
                            "promedio del sistema": 14.35}})}


def test_el_contexto_sirve_la_direccion_correcta():
    """Prueba negativa: si el contexto no dijera 'por debajo', el test no probaría nada."""
    lecturas = [c["lectura"] for c in _CTX["comparaciones"]]
    assert any("por debajo" in ll and "3.70" in ll for ll in lecturas), lecturas


def test_LA_FRASE_PUBLICADA_se_marca():
    frase = ("La capitalización contable (7.41% de activos) supera en 3.70 puntos "
             "porcentuales al promedio de su grupo.")
    assert deterministic_direction_gap_errors(_CTX, frase)


@pytest.mark.parametrize("frase", [
    "supera en 3.70 puntos porcentuales al promedio de bancos múltiples",   # etiqueta exacta
    "supera el promedio de bancos múltiples en 3.70 puntos porcentuales",   # etiqueta en la cuña
    "excede en 3.70 puntos porcentuales el promedio de su grupo",
    "sobrepasa en 3.70 puntos porcentuales la mediana del grupo",
])
def test_toda_forma_verbal_de_afirmar_lo_contrario_se_marca(frase):
    assert deterministic_direction_gap_errors(_CTX, f"El patrimonio {frase}.")


@pytest.mark.parametrize("frase", [
    "queda 3.70 puntos porcentuales por debajo del promedio de bancos múltiples",
    "es inferior en 3.70 puntos porcentuales al promedio de su grupo",
    "se ubica por debajo del promedio de bancos múltiples en 3.70 puntos porcentuales",
])
def test_la_prosa_CORRECTA_no_se_marca(frase):
    assert deterministic_direction_gap_errors(_CTX, f"El patrimonio {frase}.") == []


def test_ante_magnitudes_EMPATADAS_el_guard_se_calla():
    """Si dos comparaciones comparten la magnitud y la etiqueta viene parafraseada, no hay
    forma de decidir cuál se citaba. Gritar en falso vuelve al detector ruido que se aprende
    a ignorar — y un falso positivo acá VETA un informe correcto."""
    ctx = {"comparaciones": comparaciones_vs_referencia(
        {"a": 5.0, "b": 15.0},
        {"a": {"promedio del sistema": 8.0},        # −3.00, por debajo
         "b": {"promedio de bancos múltiples": 12.0}})}  # +3.00, por encima
    assert deterministic_direction_gap_errors(
        ctx, "El indicador supera en 3.00 puntos porcentuales al promedio de su grupo.") == []


def test_sin_palabra_de_referencia_no_se_parea_por_magnitud():
    """El pareo por magnitud solo se habilita si la cola NOMBRA una referencia. Sin eso,
    cualquier frase con un número y una unidad competiría por una comparación del contexto."""
    assert deterministic_direction_gap_errors(
        _CTX, "El plan de capital contempla un refuerzo de 3.70 puntos porcentuales.") == []
