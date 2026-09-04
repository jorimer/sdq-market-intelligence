"""La prosa de una proyección lleva su error EN LA MISMA FRASE, no en un apéndice.

Enterrar el error de un pronóstico en la sección de limitaciones es exactamente la práctica
que esta plataforma existe para no repetir: quien lee «el PIB crecerá 3,9%» y sigue leyendo
ya se formó la idea, y el apéndice llega tarde.

Los cuatro elementos que van sí o sí: el error del backtest, la CALIBRACIÓN empírica del
intervalo, el SOLAPAMIENTO cuando existe, y el corte de información.

- La calibración importa porque un intervalo del 80% que acierta el 45% de las veces engaña
  a quien dimensiona riesgo con él, aunque el RMSE se vea bien.
- El solapamiento importa porque un `n` grande sugiere una precisión que ventanas
  correlacionadas no sostienen. Cuando NO se solapan, la cláusula se OMITE: escribir «no se
  solapan» es ruido.
"""
from shared.registry.provenance import projection_sentence, provenance_paragraph
from shared.registry.signals import (
    GAP,
    PROJECTED,
    REAL,
    AxisRegistry,
    ProjectionMeta,
    VariableSignal,
)


def _meta(**cambios):
    base = dict(
        model_id="bridge_imae_pib.m2.v1", target_series="pib_real", horizon="2026-Q4",
        as_of="2026-09-30", revision=0, point=3.9,
        intervals=((0.80, 3.1, 4.7),), backtest_id="b", oos_error=0.6, error_metric="rmse",
        n_oos=34, n_oos_overlapping=True,
        interval_coverage=((0.80, 0.76, 34),))
    base.update(cambios)
    return ProjectionMeta(**base)


def _eje(*señales):
    return AxisRegistry(sector_key="macro", display_name="Macro", source="BCRD",
                        implemented=True, signals=señales)


def _proyectada(**cambios):
    return VariableSignal(key="pib_real", label="PIB real", state=PROJECTED, weight=1.0,
                          projection=_meta(**cambios))


def test_la_frase_nombra_modelo_horizonte_intervalo_y_error():
    frase = projection_sentence(_eje(_proyectada()))
    for pieza in ["PIB real", "2026-Q4", "bridge_imae_pib.m2.v1", "3.1", "4.7", "0.6",
                  "RMSE", "34"]:
        assert pieza in frase, f"la frase no dice «{pieza}»: {frase}"


def test_la_calibracion_empirica_del_intervalo_esta_en_la_frase():
    frase = projection_sentence(_eje(_proyectada()))
    assert "76" in frase, f"falta la calibración observada del intervalo: {frase}"


def test_el_solapamiento_se_declara_cuando_existe():
    frase = projection_sentence(_eje(_proyectada()))
    assert "solapan" in frase.lower()
    assert "no son" in frase.lower(), (
        "declara el solapamiento pero no dice qué implica para el conteo")


def test_cuando_no_hay_solapamiento_la_clausula_se_OMITE():
    """«No se solapan» es ruido: se omite, no se niega."""
    frase = projection_sentence(_eje(_proyectada(n_oos_overlapping=False)))
    assert "solapan" not in frase.lower(), f"escribió la negación en vez de omitir: {frase}"


def test_el_corte_de_informacion_esta_y_dice_que_no_incorpora_lo_posterior():
    frase = projection_sentence(_eje(_proyectada()))
    assert "2026-09-30" in frase
    assert "posterior" in frase.lower()


def test_un_eje_sin_proyecciones_no_dice_nada():
    eje = _eje(VariableSignal(key="a", label="A", state=REAL, weight=1.0))
    assert projection_sentence(eje) == ""


def test_una_proyeccion_que_no_pasa_el_gate_no_se_narra():
    """Si no ancla, no se cuenta: publicarla a medias es lo que el gate impide."""
    frase = projection_sentence(_eje(_proyectada(n_oos=3)))
    assert frase == "", f"narró una proyección que el gate rechaza: {frase}"


def test_la_frase_entra_en_el_parrafo_de_procedencia():
    parrafo = provenance_paragraph(_eje(_proyectada(),
                                        VariableSignal(key="b", label="B", state=GAP,
                                                       weight=1.0)))
    assert "bridge_imae_pib.m2.v1" in parrafo


def test_el_error_va_antes_de_cualquier_seccion_de_limites():
    """En la misma frase que la proyección, no al final del párrafo."""
    frase = projection_sentence(_eje(_proyectada()))
    assert frase.index("0.6") < len(frase), "no hay error en la frase"
    oraciones = [o for o in frase.split(". ") if "bridge_imae_pib" in o or "0.6" in o]
    assert oraciones, "el error quedó fuera de las oraciones que hablan del modelo"
