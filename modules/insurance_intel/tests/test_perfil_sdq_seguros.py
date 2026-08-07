"""Perfil SDQ en seguros — Fase 2 (spec §5.9)."""
import pytest

from modules.insurance_intel.scoring.perfil_sdq import (
    MIN_EJERCICIOS,
    bandas_ejecucion_por_combined,
    calcular_ejes,
    metricas_del_ciclo,
    score_reaseguro,
)


def _ejercicios(n, loss=0.35, exp=0.30, cesion=0.30):
    return {str(2018 + i): {"loss": loss, "exp": exp, "cesion": cesion} for i in range(n)}


# ── Ejecución mide el CICLO, no el último año ──────────────────────────────────

def test_ejecucion_promedia_el_ciclo_no_el_ultimo_ano():
    """Un año excepcional no debe reclasificar a una aseguradora.

    Caso real del panel: Aseguradora Agropecuaria da 71.5% de combined en 2024 y 92.5% en
    el promedio de 5 años — "excelente" o "mediocre" según qué corte se mire.
    """
    e = _ejercicios(5, loss=0.60, exp=0.35)      # combined 95% sostenido
    e["2022"] = {"loss": 0.20, "exp": 0.25, "cesion": 0.30}   # un año excepcional: 45%
    c = metricas_del_ciclo(e)
    # El promedio queda mucho más cerca del comportamiento sostenido (95%) que del año
    # excepcional (45%): un ejercicio suelto no reclasifica a la aseguradora.
    assert abs(c["combined_promedio"] - 0.95) < abs(c["combined_promedio"] - 0.45)
    assert len(c["años"]) == 5


def test_sin_ciclo_suficiente_no_se_fabrica_promedio():
    """Menos de 3 ejercicios no es un ciclo: Ejecución se declara ausente."""
    assert metricas_del_ciclo(_ejercicios(MIN_EJERCICIOS - 1)) is None
    assert metricas_del_ciclo({}) is None
    e = calcular_ejes(None, 2.5, 1.8)
    assert e["ejecucion"] is None and e["ejercicios"] == []


def test_la_ventana_toma_los_ejercicios_MAS_RECIENTES():
    c = metricas_del_ciclo(_ejercicios(7))
    assert c["años"] == ["2020", "2021", "2022", "2023", "2024"]


# ── Reaseguro: U invertida ─────────────────────────────────────────────────────

def test_reaseguro_penaliza_los_dos_extremos():
    """Cesión casi nula = desprotección; cesión casi total = fronting."""
    assert score_reaseguro(0.0) < 50
    assert score_reaseguro(0.95) < 50
    assert score_reaseguro(0.30) == 100.0


def test_la_banda_intermedia_es_plana_a_proposito():
    """Entre 5% y 70% el dato no distingue "sano" de "muy sano" — haría falta un benchmark
    del mercado reasegurador caribeño que no tenemos. No se inventa precisión."""
    assert score_reaseguro(0.10) == score_reaseguro(0.40) == score_reaseguro(0.65) == 100.0


def test_reaseguro_sin_dato_es_none_no_cero():
    assert score_reaseguro(None) is None


# ── Composición de Resiliencia ─────────────────────────────────────────────────

def test_escala_ya_no_participa_de_resiliencia():
    """Con reaseguro medido de verdad, el proxy de tamaño deja de hacer falta (§5.5)."""
    from modules.insurance_intel.scoring.perfil_sdq import PESOS_RESILIENCIA
    assert "escala" not in PESOS_RESILIENCIA
    assert set(PESOS_RESILIENCIA) == {"solvencia", "liquidez", "reaseguro", "volatilidad_loss"}
    assert sum(PESOS_RESILIENCIA.values()) == pytest.approx(1.0)


def test_resiliencia_renormaliza_sobre_las_dimensiones_presentes():
    """Una dimensión ausente no cuenta como cero: se excluye y se declara la cobertura."""
    completo = calcular_ejes(metricas_del_ciclo(_ejercicios(5)), 2.5, 1.8)
    sin_liquidez = calcular_ejes(metricas_del_ciclo(_ejercicios(5)), 2.5, None)
    assert completo["cobertura_resiliencia"] == pytest.approx(1.0)
    assert sin_liquidez["cobertura_resiliencia"] == pytest.approx(0.80)
    assert sin_liquidez["dimensiones"]["liquidez"] is None


def test_la_volatilidad_del_loss_ratio_es_distinta_de_su_nivel():
    """El ISF mide el NIVEL de siniestralidad; para aguantar un shock importa la estabilidad.
    Dos aseguradoras con el MISMO loss promedio y distinta varianza no son equivalentes."""
    estable = {str(2020 + i): {"loss": 0.40, "exp": 0.30, "cesion": 0.3} for i in range(5)}
    volatil = {str(2020 + i): {"loss": v, "exp": 0.30, "cesion": 0.3}
               for i, v in enumerate([0.10, 0.70, 0.15, 0.65, 0.40])}
    ce, cv = metricas_del_ciclo(estable), metricas_del_ciclo(volatil)
    assert ce["combined_promedio"] == pytest.approx(cv["combined_promedio"], abs=0.01)
    assert cv["loss_volatilidad"] > ce["loss_volatilidad"]
    ee = calcular_ejes(ce, 2.5, 1.8)
    ev = calcular_ejes(cv, 2.5, 1.8)
    assert ee["resiliencia"] > ev["resiliencia"]


# ── Bandas de Ejecución ────────────────────────────────────────────────────────

def test_bandas_de_ejecucion_anclan_en_el_breakeven():
    """A diferencia de banca, en seguros SÍ existe el ancla económica: combined 100%."""
    assert bandas_ejecucion_por_combined(0.70) == "Sobresaliente"
    assert bandas_ejecucion_por_combined(0.95) == "Competitiva"
    assert bandas_ejecucion_por_combined(1.05) == "Rezagada"
    assert bandas_ejecucion_por_combined(1.30) == "Deficiente"
    assert bandas_ejecucion_por_combined(None) is None
    # El corte entre Competitiva y Rezagada ES el breakeven, no un número redondo cualquiera.
    assert bandas_ejecucion_por_combined(0.999) == "Competitiva"
    assert bandas_ejecucion_por_combined(1.001) == "Rezagada"
