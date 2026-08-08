"""Perfil SDQ — motor de dos ejes (Fase 1: banca + fiduciarias)."""
import pytest

from modules.banking_score.scoring.perfil_sdq import (
    banda_ejecucion,
    banda_resiliencia,
    calcular_ejes,
    correlacion,
    cortes_ejecucion,
    perfil_panel,
)

_SUBS = {"solidez": 80.0, "calidad": 70.0, "eficiencia": 90.0,
         "liquidez": 60.0, "diversificacion": 50.0}


def test_los_ejes_reagrupan_sin_recalibrar():
    """Resiliencia = 4 componentes renormalizados; Ejecución = eficiencia sola.

    El spec (§2.3) es explícito: no se tocan los pesos relativos, se renormaliza el peso
    DENTRO de cada eje. Con el perfil de banca múltiple (40/30/15/10/5), Resiliencia sale
    de solidez+calidad+liquidez+diversificación sobre 85%.
    """
    e = calcular_ejes(_SUBS, "banca_multiple")
    esperado = (80 * .40 + 70 * .30 + 60 * .10 + 50 * .05) / .85
    assert e["resiliencia"] == pytest.approx(esperado, abs=0.05)
    assert e["ejecucion"] == pytest.approx(90.0, abs=0.05)


def test_funciona_con_los_seis_perfiles_de_peso():
    """La reagregación es genérica: el spec trata dos tipos, el sistema tiene seis."""
    for tipo in ("banca_multiple", "aap", "banco_ahorro_credito",
                 "corporacion_credito", "cambiaria", "fiduciaria"):
        e = calcular_ejes(_SUBS, tipo)
        assert 0 <= e["resiliencia"] <= 100 and 0 <= e["ejecucion"] <= 100


def test_un_subcomponente_ausente_no_se_cuenta_como_cero():
    """N/D se excluye y el peso se renormaliza — nunca se acredita dato faltante."""
    sin_calidad = dict(_SUBS, calidad=None)
    e = calcular_ejes(sin_calidad, "banca_multiple")
    esperado = (80 * .40 + 60 * .10 + 50 * .05) / .55
    assert e["resiliencia"] == pytest.approx(esperado, abs=0.05)


def test_bandas_de_resiliencia_heredan_los_cortes_del_isf():
    assert banda_resiliencia(80) == "Sólida"
    assert banda_resiliencia(62) == "Adecuada"
    assert banda_resiliencia(50) == "En vigilancia"
    assert banda_resiliencia(20) == "Frágil"
    assert banda_resiliencia(None) is None


def test_bandas_de_ejecucion_son_relativas_al_panel():
    """Ejecución no tiene un breakeven análogo al índice regulatorio: sus cortes salen
    de los cuartiles del panel comparable, y sin panel no se inventa banda."""
    cortes = cortes_ejecucion([10, 20, 30, 40, 50, 60, 70, 80])
    assert banda_ejecucion(75, cortes) == "Sobresaliente"
    assert banda_ejecucion(48, cortes) == "Competitiva"
    assert banda_ejecucion(30, cortes) == "Rezagada"
    assert banda_ejecucion(12, cortes) == "Deficiente"
    assert banda_ejecucion(50, None) is None
    assert cortes_ejecucion([1, 2]) is None  # panel insuficiente


def test_los_cortes_se_calculan_por_TIPO_no_sobre_el_universo():
    """La distribución de Ejecución difiere demasiado entre familias para compartir cortes.

    La brecha entre familias es del orden de 20 puntos de mediana, medida en producción y
    recomputada en cada corte (el endpoint la expone en `medianas_ejecucion_por_tipo`; no se
    fija acá porque cada recalibración la mueve). Con cortes únicos, casi toda la
    intermediación cambiaria caería en "Deficiente" y casi toda la banca múltiple en
    "Sobresaliente" — describiendo la diferencia entre dos modelos de negocio como si fuera
    diferencia de desempeño.
    """
    bajos = [{"entity_type": "cambiaria", "sub_scores": dict(_SUBS, eficiencia=v)}
             for v in range(10, 22)]           # 12 entidades, eficiencia 10-21
    altos = [{"entity_type": "banca_multiple", "sub_scores": dict(_SUBS, eficiencia=v)}
             for v in range(80, 92)]           # 12 entidades, eficiencia 80-91
    res = perfil_panel(bajos + altos)
    c = res["cortes_por_tipo"]
    assert c["cambiaria"]["origen"] == "propios" and c["banca_multiple"]["origen"] == "propios"
    # El mejor de cada familia es "Sobresaliente" EN SU FAMILIA, aunque sus niveles
    # absolutos no tengan nada que ver entre sí.
    mejor_cam = max((e for e in res["entidades"] if e["entity_type"] == "cambiaria"),
                    key=lambda e: e["ejecucion"])
    mejor_bm = max((e for e in res["entidades"] if e["entity_type"] == "banca_multiple"),
                   key=lambda e: e["ejecucion"])
    assert mejor_cam["banda_ejecucion"] == "Sobresaliente"
    assert mejor_bm["banda_ejecucion"] == "Sobresaliente"


def test_panel_chico_usa_los_cortes_del_universo_y_lo_declara():
    """Con menos de 12 entidades no hay cuartiles propios confiables — se declara el origen."""
    chico = [{"entity_type": "fiduciaria", "sub_scores": dict(_SUBS, eficiencia=v)}
             for v in (30, 50, 70, 90)]
    grande = [{"entity_type": "cambiaria", "sub_scores": dict(_SUBS, eficiencia=v)}
              for v in range(10, 30)]
    res = perfil_panel(chico + grande)
    assert res["cortes_por_tipo"]["fiduciaria"]["origen"] == "universo"
    assert all(e["cortes_origen"] == "universo"
               for e in res["entidades"] if e["entity_type"] == "fiduciaria")


def test_regla_de_n_chico_exige_posicion_relativa_visible():
    """Con universo chico la banda sola engaña: "Sobresaliente" entre 4 dice menos que
    entre 42. El reporte debe mostrar la posición junto a la banda (§4.2)."""
    chico = [{"entity_type": "fiduciaria", "sub_scores": dict(_SUBS, eficiencia=v)}
             for v in (30, 50, 70, 90)]
    res = perfil_panel(chico)
    for e in res["entidades"]:
        assert e["requiere_posicion_visible"] is True
        assert e["universo"] == 4 and 1 <= e["posicion_ejecucion"] <= 4
    # El de mayor Ejecución es el 1/4.
    assert max(res["entidades"], key=lambda e: e["ejecucion"])["posicion_ejecucion"] == 1


def test_gate_de_correlacion():
    """§8: si los ejes correlacionan >0.7-0.8 son la misma información con dos etiquetas."""
    assert correlacion([1, 2, 3, 4], [1, 2, 3, 4]) == pytest.approx(1.0)
    assert correlacion([1, 2, 3, 4], [4, 3, 2, 1]) == pytest.approx(-1.0)
    assert correlacion([5, 5, 5], [1, 2, 3]) is None   # sin dispersión, no hay correlación
    assert correlacion([1], [1]) is None
