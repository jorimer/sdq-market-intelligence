"""Perfil SDQ en seguros — Fase 2 (spec §5.9)."""
import pytest

from modules.insurance_intel.scoring.perfil_sdq import (
    MIN_EJERCICIOS,
    banda_ejecucion,
    bandas_ejecucion_por_combined,
    calcular_ejes,
    metricas_del_ciclo,
    score_ejecucion_desde_combined,
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

def test_la_conversion_pone_a_seguros_en_la_misma_escala():
    """§5.2 — el hueco que cerró la nota post-v1.3.

    El combined ratio es un porcentaje donde MENOS es mejor; Ejecución en los otros tres
    sectores es un índice 0-100 donde MÁS es mejor. Sin conversión explícita, seguros quedaba
    en una escala paralela y rompía la promesa de un lenguaje único entre sectores.

    La pendiente no es un número nuevo: sale de los tres cortes que el §5.9 ya fijaba sobre
    combined ratio, que calzan EXACTAMENTE con los tres límites de banda de §4.
    """
    assert score_ejecucion_desde_combined(0.90) == 75.0   # borde de Sobresaliente
    assert score_ejecucion_desde_combined(1.00) == 60.0   # breakeven → borde de Competitiva
    assert score_ejecucion_desde_combined(1.10) == 45.0   # borde de Rezagada
    assert score_ejecucion_desde_combined(None) is None
    # Clampeada a [0, 100]: un combined ratio absurdo no produce un score fuera de escala.
    assert score_ejecucion_desde_combined(0.10) == 100.0
    assert score_ejecucion_desde_combined(8.31) == 0.0    # Creciendo Seguros, CR 831%


def test_las_bandas_son_las_MISMAS_de_los_otros_sectores():
    """Los cortes de §4 (75/60/45), no un sistema propio de seguros."""
    from modules.pension_intel.scoring.perfil_sdq import banda_ejecucion as banda_pensiones
    for score in (95.0, 75.0, 74.9, 60.0, 45.0, 10.0):
        assert banda_ejecucion(score) == banda_pensiones(score), (
            f"seguros y pensiones deben coincidir en {score}")
    assert banda_ejecucion(None) is None


def test_el_breakeven_cae_en_el_borde_de_competitiva():
    """Breakeven es aceptable, no sobresaliente — y el corte de 100% es el único con ancla
    económica real de los tres."""
    assert bandas_ejecucion_por_combined(0.999) == "Competitiva"
    assert bandas_ejecucion_por_combined(1.001) == "Rezagada"
    assert bandas_ejecucion_por_combined(0.899) == "Sobresaliente"
    assert bandas_ejecucion_por_combined(1.101) == "Deficiente"


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


# ─── Base devengada/incurrida — revisión actuarial 2026-08 ────────────────────
# Defecto encontrado por revisión actuarial externa: el combined ratio era PAGADO sobre
# SUSCRITO, numerador y denominador en distinta base. El catálogo SIS tiene la estructura
# constitución (sección 5, presente ejercicio) / liberación (sección 4, anterior), así que
# ambas magnitudes SIEMPRE fueron computables.

class TestBaseDevengadaIncurrida:

    # El extractor descarta la hoja que no tenga sección de ACTIVO, así que todo fixture
    # lleva un balance mínimo que además cuadra (A = P + Pat) para no disparar el warning.
    _BALANCE = [
        ("1", "ACTIVO", None), ("1101", "INVERSIONES", None), ("110101", "Inv", 5000.0),
        ("2", "PASIVO", None), ("2101", "RESERVAS", None), ("210101", "Res", 3000.0),
        ("3", "PATRIMONIO", None), ("3101", "CAPITAL", None), ("310101", "Cap", 2000.0),
    ]

    def _hoja(self, filas):
        """Filas (codigo, descripcion, valor) → lo que consume ``_extract_sheet``."""
        return [(c, d, v) for c, d, v in (self._BALANCE + list(filas))]

    def test_la_prima_devengada_ajusta_por_reserva_de_riesgos_en_curso(self):
        from modules.insurance_intel.external.audited_excel_extractor import _extract_sheet
        f = _extract_sheet(self._hoja([
            ("4301", "PRIMAS SUSCRITAS", None), ("430101", "Vehículos", 1000.0),
            ("4310", "RESERVAS PARA RIESGOS EN CURSO DEL EJERCICIO ANTERIOR", None),
            ("431001", "Liberación", 300.0),
            ("5311", "RESERVAS PARA RIESGOS EN CURSO DEL PRESENTE EJERCICIO", None),
            ("531101", "Constitución", 400.0),
            ("5301", "RECLAMACIONES PAGADAS POR SINIESTROS", None), ("530101", "Pagado", 500.0),
        ]), "X", "2024")
        assert f is not None
        # 1000 + 300 liberada − 400 constituida = 900
        assert f.primas_devengadas == 900.0
        assert f.primas == 1000.0   # la escrita se conserva, no se pisa

    def test_el_incurrido_suma_otras_prestaciones_y_resta_salvamentos(self):
        from modules.insurance_intel.external.audited_excel_extractor import _extract_sheet
        f = _extract_sheet(self._hoja([
            ("4301", "PRIMAS SUSCRITAS", None), ("430101", "P", 1000.0),
            ("5301", "RECLAMACIONES PAGADAS POR SINIESTROS", None), ("530101", "S", 500.0),
            ("5102", "OTRAS PRESTACIONES PAGADAS", None), ("510201", "O", 80.0),
            ("4309", "SALVAMENTOS Y RECUPERACIONES", None), ("430901", "R", 30.0),
        ]), "X", "2024")
        # 500 pagado + 80 otras prestaciones − 30 salvamentos = 550
        assert f.siniestros_incurridos == 550.0
        assert f.otras_prestaciones == 80.0
        assert f.siniestros == 500.0   # el pagado sigue disponible aparte

    def test_lo_A_CARGO_DE_REASEGURADORES_no_entra_en_la_base_bruta(self):
        """Sin la exclusión, la contrapartida cedida contaminaría una medida bruta."""
        from modules.insurance_intel.external.audited_excel_extractor import _extract_sheet
        f = _extract_sheet(self._hoja([
            ("4301", "PRIMAS SUSCRITAS", None), ("430101", "P", 1000.0),
            ("5311", "RESERVAS PARA RIESGOS EN CURSO DEL PRESENTE EJERCICIO", None),
            ("531101", "C", 400.0),
            ("5312", "RESERVAS PARA RIESGOS EN CURSO A CARGO DE REASEGURADORES DEL PRESENTE",
             None), ("531201", "cedida", 250.0),
            ("5301", "RECLAMACIONES PAGADAS POR SINIESTROS", None), ("530101", "S", 100.0),
        ]), "X", "2024")
        assert f.primas_devengadas == 600.0   # 1000 − 400, la de 250 NO participa

    def test_el_panel_omite_el_ejercicio_sin_base_nueva_en_vez_de_mezclar(self):
        """Un ejercicio viejo sin devengada no debe caer al pagado-sobre-suscrito:
        mezclar bases entre compañías produce un ranking sin sentido."""
        from modules.insurance_intel.scoring.perfil_sdq import metricas_del_ciclo
        # metricas_del_ciclo recibe ya el dict por año; el filtrado ocurre aguas arriba,
        # así que acá se verifica que con menos de 3 ejercicios NO se emite ciclo.
        assert metricas_del_ciclo({"2023": {"loss": .5, "exp": .3, "cesion": .2},
                                   "2024": {"loss": .5, "exp": .3, "cesion": .2}}) is None


# ─── Ciclo ponderado por exposición ───────────────────────────────────────────
# Un promedio simple da el mismo peso a un ejercicio de 3 MM de prima que a uno de 30, y
# destruye la medición de cualquier compañía que haya cambiado de escala. Medido en
# producción: HYLSEG 118.9% simple contra 89.0% ponderado; UNIT 2.584% contra 343%.

class TestCicloPonderadoPorExposicion:

    def _ej(self, *pares):
        """(año, primas, loss, exp) → el dict que consume metricas_del_ciclo."""
        return {a: {"primas": p, "loss": lo, "exp": ex, "cesion": 0.2}
                for a, p, lo, ex in pares}

    def test_un_ejercicio_diminuto_no_pesa_igual_que_uno_grande(self):
        from modules.insurance_intel.scoring.perfil_sdq import metricas_del_ciclo
        c = metricas_del_ciclo(self._ej(
            ("2020", 1_000_000.0, 2.0, 1.0),      # combined 300%, exposición mínima
            ("2023", 50_000_000.0, 0.5, 0.3),     # combined  80%
            ("2024", 50_000_000.0, 0.5, 0.3),     # combined  80%
        ))
        assert c["ponderado_por_exposicion"] is True
        # Simple daría (3.0+0.8+0.8)/3 = 1.533; ponderado ≈ 0.822
        assert c["combined_promedio"] == pytest.approx(0.8218, abs=1e-3)

    def test_equivale_a_sumar_numeradores_sobre_sumar_denominadores(self):
        """Forma estándar del combined ratio de ciclo: Σcosto / Σprima devengada."""
        from modules.insurance_intel.scoring.perfil_sdq import metricas_del_ciclo
        años = self._ej(("2022", 10.0, 0.6, 0.3), ("2023", 20.0, 0.7, 0.2),
                        ("2024", 70.0, 0.5, 0.4))
        c = metricas_del_ciclo(años)
        num = sum(v["primas"] * (v["loss"] + v["exp"]) for v in años.values())
        den = sum(v["primas"] for v in años.values())
        assert c["combined_promedio"] == pytest.approx(num / den)

    def test_la_volatilidad_tambien_se_pondera(self):
        """Los ejercicios de arranque inflaban σ y castigaban Resiliencia sin exposición."""
        from modules.insurance_intel.scoring.perfil_sdq import metricas_del_ciclo
        c = metricas_del_ciclo(self._ej(
            ("2020", 1.0, 3.0, 0.3), ("2023", 100.0, 0.5, 0.3), ("2024", 100.0, 0.5, 0.3)))
        # Con σ simple el año atípico domina; ponderado queda casi plano.
        assert c["loss_volatilidad"] < 0.2

    def test_sin_volumen_cae_al_promedio_simple_y_lo_declara(self):
        """Un peso ausente no debe borrar la observación."""
        from modules.insurance_intel.scoring.perfil_sdq import metricas_del_ciclo
        sin_peso = {a: {"loss": lo, "exp": 0.3, "cesion": 0.2}
                    for a, lo in (("2022", 0.5), ("2023", 0.6), ("2024", 0.7))}
        c = metricas_del_ciclo(sin_peso)
        assert c["ponderado_por_exposicion"] is False
        assert c["combined_promedio"] == pytest.approx((0.8 + 0.9 + 1.0) / 3)


# ─── Tendencia, cobertura y ciclo comparable ─────────────────────────────────

class TestTendenciaYGuards:

    def _ej(self, *pares):
        return {a: {"primas": p, "loss": lo, "exp": ex, "cesion": 0.2}
                for a, p, lo, ex in pares}

    def test_el_nivel_no_distingue_60_a_80_de_80_a_60_pero_la_pendiente_si(self):
        """El punto central de la revisión actuarial sobre nivel vs tendencia."""
        from modules.insurance_intel.scoring.perfil_sdq import banda_tendencia, metricas_del_ciclo
        sube = metricas_del_ciclo(self._ej(("2022", 100.0, 0.3, 0.3), ("2023", 100.0, 0.4, 0.3),
                                           ("2024", 100.0, 0.5, 0.3)))
        baja = metricas_del_ciclo(self._ej(("2022", 100.0, 0.5, 0.3), ("2023", 100.0, 0.4, 0.3),
                                           ("2024", 100.0, 0.3, 0.3)))
        # Mismo nivel medio, trayectorias opuestas.
        assert sube["combined_promedio"] == pytest.approx(baja["combined_promedio"])
        assert sube["pendiente_combined"] == pytest.approx(10.0)
        assert baja["pendiente_combined"] == pytest.approx(-10.0)
        assert banda_tendencia(sube["pendiente_combined"],
                               sube["pendiente_error_estandar"]) == "Deteriora"
        assert banda_tendencia(baja["pendiente_combined"],
                               baja["pendiente_error_estandar"]) == "Mejora"

    def test_una_pendiente_que_no_se_separa_de_cero_NO_afirma_direccion(self):
        """Medido: el EE mediano de la pendiente es 2.4 pp/año. Un umbral fijo de ±1
        afirmaba dirección para 24 de 32 compañías donde el dato no la sostiene."""
        from modules.insurance_intel.scoring.perfil_sdq import banda_tendencia
        assert banda_tendencia(+1.2, 0.9) == "Sin señal"    # t = 1.33
        assert banda_tendencia(-17.3, 15.7) == "Sin señal"  # pendiente enorme, ruido mayor
        assert banda_tendencia(+2.9, 0.7) == "Deteriora"    # t = 4.14
        assert banda_tendencia(-6.7, 0.7) == "Mejora"       # t = -9.6

    def test_ajuste_perfecto_es_evidencia_MAXIMA_no_ausencia(self):
        """Residuo cero da EE=0. Tratarlo como «no se puede juzgar» invertía el sentido."""
        from modules.insurance_intel.scoring.perfil_sdq import banda_tendencia
        assert banda_tendencia(+10.0, 0.0) == "Deteriora"
        assert banda_tendencia(-10.0, 0.0) == "Mejora"
        assert banda_tendencia(0.0, 0.0) == "Sin señal"

    def test_sin_error_estandar_no_se_etiqueta(self):
        """Preferible callar a afirmar una dirección que no se puede juzgar."""
        from modules.insurance_intel.scoring.perfil_sdq import banda_tendencia
        assert banda_tendencia(5.0, None) is None
        assert banda_tendencia(None, 1.0) is None

    def test_un_salto_de_escala_marca_el_ciclo_como_NO_comparable(self):
        """UNIT: prima de 106 mil en el primer ejercicio y 132 millones en el último.
        No se corrige el número —sería fabricarlo— se declara."""
        from modules.insurance_intel.scoring.perfil_sdq import metricas_del_ciclo
        arranque = metricas_del_ciclo(self._ej(
            ("2022", 100_000.0, 5.0, 3.0), ("2023", 10_000_000.0, 0.6, 0.3),
            ("2024", 100_000_000.0, 0.5, 0.3)))
        assert arranque["ciclo_comparable"] is False
        estable = metricas_del_ciclo(self._ej(
            ("2022", 90.0, 0.5, 0.3), ("2023", 100.0, 0.5, 0.3), ("2024", 110.0, 0.5, 0.3)))
        assert estable["ciclo_comparable"] is True

    def test_sin_cobertura_suficiente_NO_se_publica_resiliencia(self):
        """Regresión: se publicaba 100.0 y 0.0 para entidades sin un solo ejercicio
        financiero, renormalizando una sola dimensión al 100%."""
        from modules.insurance_intel.scoring.perfil_sdq import calcular_ejes
        # Solo solvencia disponible (peso 0.47 < 0.50): insuficiente.
        e = calcular_ejes(None, 2.5, None)
        assert e["resiliencia"] is None
        assert e["cobertura_suficiente"] is False
        assert e["dimensiones"]["solvencia"] is not None  # la dimensión SÍ se reporta
        # Con solvencia + liquidez (0.67) sí alcanza.
        e2 = calcular_ejes(None, 2.5, 3.0)
        assert e2["resiliencia"] is not None and e2["cobertura_suficiente"] is True


def test_el_panel_resuelve_el_slug_derivado_por_truncacion_de_hoja():
    """Regresión: el nombre de hoja del Excel se trunca a 31 caracteres, así que el slug
    bajo el que se guardan las series NO es el canónico. Consultar por el canónico devolvía
    cero filas y dejaba SIN Ejecución a siete aseguradoras con primas de cientos de millones
    (Cuna Mutual, One Alliance, Cooperativa Nacional…), como si no tuvieran datos.

    El ISF ya colapsaba las variantes contra el roster; el eje no usaba ese mapa.
    """
    from modules.insurance_intel.scoring.isf import _canon_map

    class _E:
        def __init__(self, slug, name):
            self.slug, self.name = slug, name

    # Cuatro variantes reales de la misma compañía, tal como están en producción.
    ents = [_E("cuna", "Cuna Mutual"),
            _E("cuna_mutual_insurance_trustage", "Cuna Mutual Insurance(TRUSTAGE)"),
            _E("cuna_mutual_insurance_society_d", "Cuna Mutual Insurance Society D"),
            _E("otra_cosa", "Seguros Pepín, S. A.")]
    canon, heuristic = _canon_map(ents, None)   # camino heurístico, sin roster
    # Las tres variantes de Cuna colapsan a UNA sola identidad.
    identidades = {canon[e.slug][0] for e in ents[:3] if e.slug in canon}
    assert len(identidades) == 1, "las variantes de la misma compañía no colapsaron"
    # Y el mapa cubre el slug DERIVADO, que es la clave para encontrar las series.
    assert "cuna_mutual_insurance_trustage" in canon


def test_calcular_ejes_devuelve_TODAS_las_claves_que_lee_el_router():
    """Regresión de un 500 en producción.

    Se agregó `pendiente_error_estandar` al retorno de ``metricas_del_ciclo`` y al router,
    pero NO al de ``calcular_ejes``, que es el intermediario. Los 3.255 tests unitarios
    pasaron —cada pieza andaba— y el endpoint devolvía KeyError → 500, porque ninguno
    ejercitaba el CONTRATO entre motor y router.

    Este test lo fija leyendo las claves directamente del código del endpoint: si mañana el
    router lee una clave nueva, falla acá antes que en producción.
    """
    import inspect
    import re
    from modules.insurance_intel.api import router as api
    from modules.insurance_intel.scoring.perfil_sdq import calcular_ejes

    src = inspect.getsource(api.perfil_sdq)
    leidas = set(re.findall(r'ejes\["([a-z_]+)"\]', src))
    assert leidas, "no se detectaron accesos a ejes[...]; ¿cambió la forma del endpoint?"

    # Las dos rutas: con ciclo y sin ciclo. La segunda es la que reventaba.
    ciclo = {"años": ["2022", "2023", "2024"], "combined_promedio": 0.9,
             "loss_volatilidad": 0.04, "cesion_promedio": 0.2,
             "ponderado_por_exposicion": True, "pendiente_combined": 1.0,
             "pendiente_error_estandar": 0.3, "ciclo_comparable": True}
    for etiqueta, c in (("con ciclo", ciclo), ("sin ciclo", None)):
        ejes = calcular_ejes(c, 2.5, 3.0)
        faltan = leidas - set(ejes)
        assert not faltan, f"{etiqueta}: calcular_ejes no devuelve {sorted(faltan)}"
def test_la_metodologia_DECLARA_la_decision_sobre_el_ancla_por_tipo():
    """La pregunta health-vs-life NO es resoluble con este panel: n=6 en personas y el signo
    de la correlación cambia según dónde se corte la muestra. Eso no puede quedar mudo —
    un lector que ve una aseguradora de salud en «Rezagada» necesita saber que lo miramos,
    qué encontramos y por qué el ancla no se mueve.

    Fija la DECLARACIÓN, no el resultado del análisis.
    """
    import inspect

    from modules.insurance_intel.api import router as api
    from modules.insurance_intel.scoring.perfil_sdq import ANCLAJE_POR_TIPO

    texto = ANCLAJE_POR_TIPO.lower()
    for pieza in ("no es estimable", "contraejemplo", "dato regulatorio", "no se mueve"):
        assert pieza in texto, f"la declaración no menciona «{pieza}»"
    # Y tiene que llegar a la superficie junto con el tipo por fila, o no es accionable.
    src = inspect.getsource(api.perfil_sdq)
    assert "ANCLAJE_POR_TIPO" in src and '"tipo_derivado"' in src
