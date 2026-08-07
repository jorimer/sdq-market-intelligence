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


# ── Desglose por ramo (§5.6) ───────────────────────────────────────────────────

def test_el_extractor_parea_los_ramos_de_generales_por_sufijo():
    """En generales el sufijo coincide: 4301XX primas ↔ 5301XX siniestros."""
    from modules.insurance_intel.external.audited_excel_extractor import _extract_sheet
    rows = [
        ("1", "ACTIVO", None), ("1101", "INV", 700.0), ("1201", "EFE", 300.0),
        ("2", "PASIVO", None), ("2101", "RES", 500.0),
        ("3", "PATRIMONIO", None), ("3101", "CAP", 500.0),
        ("4", "INGRESOS", None), ("4301", "PRIMAS SUSCRITAS", None),
        ("430106", "VEHICULOS", 1000.0), ("430107", "AGRICOLA", 500.0),
        ("5", "GASTOS", None), ("5301", "RECLAMACIONES PAGADAS POR SINIESTROS", None),
        ("530106", "VEHICULOS", 700.0), ("530107", "AGRICOLA", 100.0),
    ]
    f = _extract_sheet(rows, "Test", "2024")
    assert f.por_ramo["vehiculos_motor"] == {"primas": 1000.0, "siniestros": 700.0}
    assert f.por_ramo["agricola_pecuario"] == {"primas": 500.0, "siniestros": 100.0}


def test_en_personas_el_mapeo_es_explicito_no_posicional():
    """Primas abre vida individual en 'primer año' + 'renovación'; siniestros la consolida.

    Emparejar por posición daría el loss ratio de vida contra siniestros de accidentes.
    """
    from modules.insurance_intel.external.audited_excel_extractor import _extract_sheet
    rows = [
        ("1", "ACTIVO", None), ("1101", "INV", 1000.0),
        ("2", "PASIVO", None), ("2101", "RES", 500.0),
        ("3", "PATRIMONIO", None), ("3101", "CAP", 500.0),
        ("4", "INGRESOS", None), ("4101", "PRIMAS SUSCRITAS", None),
        ("410101", "VIDA IND PRIMER AÑO", 300.0), ("410102", "VIDA IND RENOVACION", 200.0),
        ("410104", "ACCIDENTES PERSONALES", 400.0), ("410106", "RENTAS", 50.0),
        ("5", "GASTOS", None), ("5101", "RECLAMACIONES PAGADAS POR SINIESTRO", None),
        ("510101", "VIDA INDIVIDUAL", 150.0), ("510103", "ACCIDENTES PERSONALES", 250.0),
    ]
    f = _extract_sheet(rows, "Test", "2024")
    # Vida individual suma las dos sub-cuentas de prima contra UNA de siniestros.
    assert f.por_ramo["vida_individual"] == {"primas": 500.0, "siniestros": 150.0}
    assert f.por_ramo["accidentes_personales"] == {"primas": 400.0, "siniestros": 250.0}
    # Rentas no tiene contraparte en el catálogo: siniestros None, nunca un cero fabricado.
    assert f.por_ramo["rentas"] == {"primas": 50.0, "siniestros": None}


def test_la_dispersion_por_ramo_pondera_por_prima():
    """Sin ponderar, un ramo residual domina el resultado.

    Caso real: en Seguros Universal, naves aéreas mueve RD$14M con loss ratio 164% y salud
    mueve RD$6.022M con 71.8%. Tratarlos igual describe una anécdota, no la cartera.
    """
    from modules.insurance_intel.scoring.perfil_sdq import dispersion_loss_por_ramo
    d = dispersion_loss_por_ramo({
        "salud": {"primas": 6_000e6, "siniestros": 4_300e6},        # 71.7%, dominante
        "vehiculos_motor": {"primas": 3_600e6, "siniestros": 2_500e6},  # 69.4%
        "naves_aereas": {"primas": 14e6, "siniestros": 23e6},       # 164%, residual
    })
    assert d["n_ramos"] == 3
    # El loss ponderado queda cerca de los ramos grandes, no arrastrado por el chico.
    assert 0.68 < d["loss_ponderado"] < 0.75
    # Y la dispersión es baja pese al outlier: pesa por su participación real.
    assert d["dispersion"] < 0.15


def test_la_dispersion_descarta_los_ramos_residuales_y_los_incompletos():
    from modules.insurance_intel.scoring.perfil_sdq import dispersion_loss_por_ramo
    assert dispersion_loss_por_ramo({"a": {"primas": 100, "siniestros": 50}}) is None
    assert dispersion_loss_por_ramo(
        {"a": {"primas": 5e6, "siniestros": None}, "b": {"primas": 5e6, "siniestros": 1e6}}
    ) is None   # un solo ramo con dato completo no da dispersión
    assert dispersion_loss_por_ramo({}) is None


# ── Siniestros incurridos (§5.3) ───────────────────────────────────────────────

def test_incurridos_ajustan_por_la_variacion_de_reservas():
    from modules.insurance_intel.scoring.perfil_sdq import siniestros_incurridos
    r = siniestros_incurridos(pagados=100.0, reservas_actual=520.0, reservas_previa=500.0)
    assert r["incurridos"] == 120.0 and r["ajuste_reservas"] == 20.0
    assert r["aproximado"] is True and r["limitacion"]


def test_incurridos_sin_reserva_previa_no_se_inventan():
    from modules.insurance_intel.scoring.perfil_sdq import siniestros_incurridos
    assert siniestros_incurridos(100.0, 520.0, None) is None
    assert siniestros_incurridos(None, 520.0, 500.0) is None
