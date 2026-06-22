"""Tests del detector DETERMINISTA del guardrail numérico (cerebro).

Cubre los cuatro modos que el juez LLM dejaba pasar (delta vs mediana ligado a la base,
rango sobre la ventana, valor↔período, aporte = score×peso) más casos limpios, de
redondeo legítimo y best-effort con contexto incompleto.
"""
from shared.narrative.numeric_guard import deterministic_unsupported


def _ctx(**over):
    """Contexto de entidad (forma de ai_context_entity) para los tests."""
    base = {
        "score_global": 86.42,
        "sub_componentes": [
            {"componente": "Solidez", "score": 100.0, "peso": 0.40},
            {"componente": "Calidad", "score": 88.41, "peso": 0.30},
            {"componente": "Eficiencia", "score": 53.42, "peso": 0.15},
            {"componente": "Liquidez", "score": 76.48, "peso": 0.10},
            {"componente": "Diversificación", "score": 53.08, "peso": 0.05},
        ],
        "pares": {
            "entity_type": {"median_score": 82.65, "p75_score": 85.25},
            "sector": {"median_score": 80.18, "p75_score": 85.25},
        },
        "tendencia_score": [
            {"periodo": "2024-03", "score": 88.67},
            {"periodo": "2024-06", "score": 89.79},
            {"periodo": "2025-03", "score": 89.29},
            {"periodo": "2026-03", "score": 88.96},
            {"periodo": "2023-06", "score": 90.42},
        ],
    }
    base.update(over)
    return base


# ── (1) delta vs mediana, ligado a la base citada ──────────────────────────────

def test_delta_vs_mediana_tipo_incorrecto_se_marca():
    bad = deterministic_unsupported(_ctx(), "6.2 puntos sobre la mediana de sus pares directos")
    assert any("6.2" in f and "tipo" in f for f in bad)


def test_delta_vs_mediana_tipo_correcto_pasa():
    # 86.42 − 82.65 = 3.77
    assert deterministic_unsupported(_ctx(), "3.77 puntos sobre la mediana de sus pares") == []


def test_delta_vs_mediana_sector_se_liga_a_la_base():
    # 86.42 − 80.18 = 6.24 ; bien rotulado como sector → pasa
    assert deterministic_unsupported(
        _ctx(), "6.24 puntos por encima de la mediana del sector") == []


def test_delta_tipo_con_sector_mencionado_lejos_no_es_fp():
    # base = "grupo" (tipo) aunque "sector" aparezca después; 3.77 es el delta vs tipo → pasa
    assert deterministic_unsupported(
        _ctx(), "3.77 puntos sobre la mediana de su grupo dentro del sector bancario") == []


def test_delta_sin_qualifier_lenient_no_es_fp():
    # sin base nombrada; 6.24 casa con el delta vs sector → no se marca (lenient)
    assert deterministic_unsupported(_ctx(), "6.24 puntos por encima de la mediana") == []
    # y 3.77 casa con el delta vs tipo → tampoco
    assert deterministic_unsupported(_ctx(), "3.77 puntos sobre la mediana") == []


# ── (2) rango sobre la ventana de 12T ──────────────────────────────────────────

def test_rango_con_piso_errado_se_marca():
    bad = deterministic_unsupported(_ctx(), "score en rango 88.96–90.42 durante doce trimestres")
    assert any("rango" in f for f in bad)


def test_rango_correcto_pasa():
    assert deterministic_unsupported(
        _ctx(), "score en rango 88.67–90.42 durante doce trimestres") == []


def test_banda_redondeada_sin_decimales_no_se_marca():
    # "banda 88–90" es descripción redondeada, no claim preciso
    assert deterministic_unsupported(_ctx(), "oscila en banda 88–90 en los doce trimestres") == []


# ── (3) valor atado a período ───────────────────────────────────────────────────

def test_valor_periodo_explicito_correcto_pasa():
    assert deterministic_unsupported(_ctx(), "cayó a 88.96 en marzo 2026") == []


def test_valor_periodo_explicito_incorrecto_se_marca():
    bad = deterministic_unsupported(_ctx(), "cerró en 90.00 en marzo 2026")
    assert any("90.00" in f for f in bad)


def test_secuencia_corte_de_marzo_con_valor_de_otro_mes_se_marca():
    # 90.42 es de junio; ponerlo como corte de marzo → se marca
    bad = deterministic_unsupported(
        _ctx(), "caídas en los cortes de marzo (90.42 → 88.67 → 89.29 → 88.96)")
    assert any("90.42" in f for f in bad)


# ── (4) aporte = score×peso ─────────────────────────────────────────────────────

def test_aporte_fabricado_se_marca():
    # aportes {40.0, 26.52, 8.01, 7.65, 2.65}; ninguna suma de subconjuntos ≈ 13.0
    # (subset-sums solo producen falsos negativos por coincidencia, nunca falsos positivos)
    bad = deterministic_unsupported(_ctx(), "ambos aportan solo ~13.0 puntos combinados")
    assert any("13.0" in f for f in bad)


def test_aporte_correcto_pasa():
    # solidez 100×0.40 = 40.0
    assert deterministic_unsupported(_ctx(), "solidez aporta 40.0 puntos al global") == []


# ── limpio / redondeo / best-effort ─────────────────────────────────────────────

def test_texto_limpio_no_marca_nada():
    txt = ("El rating descansa en solidez (score 100, peso 0.40). Calidad marca 88.41. "
           "El score cayó a 88.96 en marzo 2026 desde 90.42 en junio 2023.")
    assert deterministic_unsupported(_ctx(), txt) == []


def test_contexto_incompleto_no_rompe():
    assert deterministic_unsupported({}, "cualquier cosa con 6.2 sobre la mediana") == []
    assert deterministic_unsupported({"score_global": None}, "texto 88.96") == []
