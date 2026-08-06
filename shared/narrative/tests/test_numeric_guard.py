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


def test_valor_periodo_parentetico_incorrecto_se_marca():
    # forma 'mes AAAA (VALUE)': 90.42 no es de diciembre 2026 (no existe; el de jun es 90.42)
    ctx = _ctx(tendencia_score=[
        {"periodo": "2025-12", "score": 89.27}, {"periodo": "2026-03", "score": 88.96}])
    bad = deterministic_unsupported(ctx, "cayó desde diciembre 2025 (90.42) hasta hoy")
    assert any("90.42" in f and "diciembre" in f for f in bad)


def test_valor_periodo_parentetico_no_cruza_clausula():
    # 'mes 2024) y 90.42' NO debe atribuir 90.42 a 2024 (está en la cláusula siguiente)
    ctx = _ctx(tendencia_score=[
        {"periodo": "2024-03", "score": 88.67}, {"periodo": "2023-06", "score": 90.42}])
    assert deterministic_unsupported(
        ctx, "osciló entre 88.67 (mínimo, marzo 2024) y 90.42 (máximo, junio 2023)") == []


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


# ── (5) dirección vs P75 ────────────────────────────────────────────────────────

def test_direccion_p75_invertida_se_marca():
    # score 86.42 > p75 85.25 ; decir "por debajo" invierte el lado → marca
    bad = deterministic_unsupported(_ctx(), "0.15 pts por debajo del P75 del grupo (85.25)")
    assert any("p75" in f.lower() for f in bad)


def test_direccion_p75_correcta_pasa():
    assert deterministic_unsupported(_ctx(), "1.17 pts por encima del P75 (85.25)") == []


# ── (6) afirmación de extremo ───────────────────────────────────────────────────

def test_extremo_minimo_incorrecto_se_marca():
    # 88.96 no es el mínimo de la ventana (88.67 lo es) aunque difieran <0.3
    ctx = _ctx(tendencia_score=[
        {"periodo": "2024-03", "score": 88.67}, {"periodo": "2025-03", "score": 89.29},
        {"periodo": "2026-03", "score": 88.96}, {"periodo": "2023-06", "score": 90.42}])
    bad = deterministic_unsupported(ctx, "88.96, el valor más bajo del período analizado")
    assert any("mínimo" in f for f in bad)


def test_extremo_minimo_correcto_pasa():
    ctx = _ctx(tendencia_score=[
        {"periodo": "2024-03", "score": 88.67}, {"periodo": "2026-03", "score": 88.96}])
    assert deterministic_unsupported(ctx, "88.67 es el más bajo de los doce trimestres") == []


# ── (7) conteo bajo umbral ──────────────────────────────────────────────────────

def test_extremo_de_otra_metrica_no_es_fp():
    # "ROE 85.5 el más alto del período": 85.5 no es un score de la ventana → ignorar
    ctx = _ctx(tendencia_score=[
        {"periodo": "2024-03", "score": 88.67}, {"periodo": "2026-03", "score": 88.96}])
    assert deterministic_unsupported(ctx, "el ROE de 85.5 fue el más alto del período") == []


def test_conteo_bajo_umbral_violado_se_marca():
    # últimos 4: 89.74, 89.34, 89.27, 88.96 ; "por debajo de 89.50" lo rompe 89.74
    ctx = _ctx(tendencia_score=[
        {"periodo": "2025-03", "score": 89.29}, {"periodo": "2025-06", "score": 89.74},
        {"periodo": "2025-09", "score": 89.34}, {"periodo": "2025-12", "score": 89.27},
        {"periodo": "2026-03", "score": 88.96}])
    bad = deterministic_unsupported(
        ctx, "lleva cuatro trimestres consecutivos por debajo de 89.50")
    assert any("trimestres" in f for f in bad)


def test_conteo_umbral_de_otra_metrica_no_es_fp():
    # "eficiencia dos trimestres por debajo de 60": 60 fuera del rango del score → ignorar
    ctx = _ctx(tendencia_score=[
        {"periodo": "2025-12", "score": 89.27}, {"periodo": "2026-03", "score": 88.96}])
    assert deterministic_unsupported(
        ctx, "la eficiencia cayó dos trimestres por debajo de 60") == []


# ── limpio / redondeo / best-effort ─────────────────────────────────────────────

def test_texto_limpio_no_marca_nada():
    txt = ("El rating descansa en solidez (score 100, peso 0.40). Calidad marca 88.41. "
           "El score cayó a 88.96 en marzo 2026 desde 90.42 en junio 2023.")
    assert deterministic_unsupported(_ctx(), txt) == []


def test_contexto_incompleto_no_rompe():
    assert deterministic_unsupported({}, "cualquier cosa con 6.2 sobre la mediana") == []
    assert deterministic_unsupported({"score_global": None}, "texto 88.96") == []


def test_punto_suelto_no_rompe_el_detector():
    # un '.' antes de 'sobre la mediana' no debe tirar el detector (regresion: float('.'))
    txt = "El banco es sólido. sobre la mediana de pares hay margen; aporta 40.0 puntos."
    assert isinstance(deterministic_unsupported(_ctx(), txt), list)


# ── (8) Superlativo transversal ('el mayor del sistema' donde no lidera) ──────────

def _pos_ctx():
    """Contexto con posiciones por dimensión: la entidad es #1 GLOBAL pero #2 en escala
    (lidera Popular) y #2 en solvencia (lidera Romana) — el caso del Deep Dive de pensiones."""
    return {
        "posiciones_dimension": {
            "Escala (fondos administrados / AUM)": {
                "rank": 2, "n": 7, "es_lider": False, "lider_afp": "AFP Popular"},
            "Solvencia (patrimonio/activos)": {
                "rank": 2, "n": 7, "es_lider": False, "lider_afp": "AFP Romana"},
            "Costo (comisión/AUM)": {
                "rank": 1, "n": 7, "es_lider": True, "lider_afp": "AFP Reservas"},
        }
    }


def test_superlative_escala_flagged():
    text = ("AFP Reservas administra un fondo acumulado de RD$ 348,007 millones "
            "—el mayor del sistema—, con un puntaje de 84.73.")
    flags = deterministic_unsupported(_pos_ctx(), text)
    assert any("no lidera" in f and "Escala" in f and "Popular" in f for f in flags), flags


def test_superlative_solvencia_flagged():
    text = "combina la mayor base de activos con el índice de solvencia más alto del panel."
    flags = deterministic_unsupported(_pos_ctx(), text)
    assert any("Solvencia" in f and "Romana" in f for f in flags), flags


def test_superlative_where_leader_not_flagged():
    """Si la entidad SÍ lidera la dimensión (costo), el superlativo es válido → no se marca."""
    text = "tiene la comisión más baja del sistema."
    flags = deterministic_unsupported(_pos_ctx(), text)
    assert not any("Costo" in f for f in flags), flags


def test_negated_superlative_not_flagged():
    """'No es el mayor del sistema' es un superlativo NEGADO → no es afirmación, no se marca."""
    text = "No es la solvencia más alta del panel, pero su escala compensa."
    flags = deterministic_unsupported(_pos_ctx(), text)
    assert not any("Solvencia" in f for f in flags), flags


def test_no_positions_no_crosssectional_flags():
    """Sin ``posiciones_dimension`` el patrón se salta (best-effort, no rompe)."""
    text = "es el mayor del sistema en escala."
    assert deterministic_unsupported({}, text) == []


# ── Dirección de las comparaciones ────────────────────────────────────────────
#
# Bug 2026-08-05 (BPD, full_rating): la §1 afirmó que una mora de 1.67% estaba "por debajo"
# del promedio de pares grandes (1.5%), contradiciendo la tabla del propio informe. Ambas
# cifras estaban en el contexto y eran correctas — lo invertido era el sentido, que el juez
# LLM dejó pasar. El listón de estos tests es doble: agarrar el caso real Y no gritar en
# falso sobre prosa legítima (un guard ruidoso se aprende a ignorar).

from shared.narrative.numeric_guard import deterministic_direction_errors  # noqa: E402


def _bank_ctx():
    """Contexto con la forma REAL de una sección de panorama de banca."""
    return {
        "indicators": {
            "morosidad": {"raw": 1.67, "score": 83.3},
            "solvencia": {"raw": 16.44, "score": 100.0},
            "roa": {"raw": 1.59, "score": 100.0},
            "ltd": {"raw": 88.4745, "score": 99.36},
        },
        "benchmarks": {
            "sector_averages": {"npl": 1.8, "car": 16.5, "roa": 2.1, "ltd": 78.0},
            "peer_groups": {"large_banks": {"npl_avg": 1.5, "car_avg": 15.8,
                                            "roa_avg": 2.3}},
        },
    }


def test_real_bpd_inverted_comparison_is_flagged():
    """El caso exacto que llegó al PDF de cliente."""
    text = ("La tasa de mora (1.67%) se sitúa por debajo del umbral de alerta regulatoria "
            "y del promedio del grupo de bancos grandes (1.5%), con el 98.25% de la "
            "cartera en la categoría de menor riesgo.")
    flags = deterministic_direction_errors(_bank_ctx(), text)
    assert any("morosidad" in f for f in flags), flags


def test_correct_direction_against_sector_not_flagged():
    """La MISMA mora sí está por debajo del sistema (1.8%): afirmación válida."""
    text = "la morosidad de 1.67% es inferior a la del promedio sectorial (1.8%)."
    assert deterministic_direction_errors(_bank_ctx(), text) == []


def test_correct_direction_above_peers_not_flagged():
    text = "la mora de 1.67% se ubica por encima del promedio de pares grandes (1.5%)."
    assert deterministic_direction_errors(_bank_ctx(), text) == []


def test_prospective_threshold_not_flagged():
    """Falso positivo real: umbrales prospectivos que no son ni el valor de la entidad ni
    una referencia conocida ('si la solvencia cae por debajo de 18%…')."""
    text = ("Una caída de la solvencia por debajo de 18% —que comprimiría el margen sobre "
            "el mínimo regulatorio de 15%— o un incremento de la ratio préstamos-depósitos "
            "por encima del 93% activaría la revisión.")
    assert deterministic_direction_errors(_bank_ctx(), text) == []


def test_chained_clauses_not_flagged():
    """Falso positivo real: dos cláusulas independientes unidas por punto y coma."""
    text = ("Un ROA de 1.0% o superior abriría espacio para ampliar la línea; un "
            "estancamiento por debajo de 0.5% obligaría a revisar.")
    assert deterministic_direction_errors(_bank_ctx(), text) == []


def test_cross_indicator_numbers_not_paired():
    """Falso positivo real: una fila de tabla pegada a la frase siguiente mezcla números de
    indicadores DISTINTOS (ROA 1.59 con CAR de pares 15.8). No deben parearse."""
    text = ("ROA 1.59% 2.3% 2.1% Costo-ingreso 44.36% La capitalización del banco (16.44%) "
            "supera la media del grupo grande (15.8%).")
    assert deterministic_direction_errors(_bank_ctx(), text) == []


def test_reference_must_follow_the_marker():
    """La entidad debe ser el SUJETO: con los operandos al revés no se afirma nada sobre
    ella, así que no se juzga (mejor callar que marcar mal)."""
    text = "el promedio de pares grandes (1.5%) está por debajo de la mora de 1.67%."
    assert deterministic_direction_errors(_bank_ctx(), text) == []


def test_indistinguishable_values_not_flagged():
    """Si a la precisión citada entidad y referencia coinciden, la dirección no es
    afirmable ni refutable."""
    ctx = {"indicators": {"morosidad": {"raw": 1.52}},
           "benchmarks": {"peer_groups": {"large_banks": {"npl_avg": 1.5}}}}
    text = "la mora de 1.5% está por debajo del promedio de pares (1.5%)."
    assert deterministic_direction_errors(ctx, text) == []


def test_rounded_citation_still_matches():
    """Citar 1.7% para una mora real de 1.67% es redondeo legítimo — y sigue siendo un
    error de dirección contra 1.5%."""
    text = "la mora de 1.7% se sitúa por debajo del promedio de pares grandes (1.5%)."
    flags = deterministic_direction_errors(_bank_ctx(), text)
    assert any("morosidad" in f for f in flags), flags


def test_subcomponent_context_key_supported():
    """Las secciones de sub-componente usan la clave 'indicadores' (en español)."""
    ctx = {"indicadores": {"morosidad": {"raw": 1.67}},
           "benchmarks": {"peer_groups": {"large_banks": {"npl_avg": 1.5}}}}
    text = "una mora de 1.67%, inferior a la del promedio de pares grandes (1.5%)."
    assert deterministic_direction_errors(ctx, text)


def test_unknown_indicator_is_never_judged():
    """Sin benchmark reconocido no se emite veredicto (seguros/pensiones usan otras claves)."""
    ctx = {"indicators": {"siniestralidad": {"raw": 80.0}}, "benchmarks": {}}
    text = "una siniestralidad de 80.0% por debajo del promedio de 60.0%."
    assert deterministic_direction_errors(ctx, text) == []


def test_empty_and_missing_context_are_safe():
    assert deterministic_direction_errors({}, "texto sin cifras") == []
    assert deterministic_direction_errors(_bank_ctx(), "") == []


def test_contrastive_pair_not_flagged_bpd():
    """Falso positivo REAL (BPD, sección Liquidez): 'supera el mínimo (15%) PERO se sitúa
    por debajo del promedio (28.5%)' es prosa CORRECTA — el 28.5 es operando del segundo
    marcador, no del primero."""
    ctx = {"indicators": {"liquidez_inmediata": {"raw": 22.2888}},
           "benchmarks": {"sector_averages": {"liquidity_ratio": 28.5}}}
    text = ("La liquidez inmediata de 22.29% supera el mínimo regulatorio (15%) pero se "
            "sitúa por debajo del promedio sectorial (28.5%), lo que indica márgenes de "
            "corto plazo más ajustados.")
    assert deterministic_direction_errors(ctx, text) == []


def test_contrastive_chain_with_two_references_not_flagged_lafise():
    """Falso positivo REAL (Lafise): 'supera el mínimo de 10.0% y el piso de 10.5%, pero se
    sitúa por debajo del promedio (16.5%) y por debajo de la banca mediana (17.2%)' — las
    tres afirmaciones son correctas y cada referencia pertenece a su propio marcador."""
    ctx = {"indicators": {"solvencia": {"raw": 11.57}},
           "benchmarks": {"sector_averages": {"car": 16.5},
                          "peer_groups": {"medium_banks": {"car_avg": 17.2}}}}
    text = ("El índice de adecuación de capital (ICAP) de 11.57% supera el mínimo "
            "regulatorio de 10.0% y el piso de Basilea III de 10.5%, pero se sitúa 4.93 "
            "puntos porcentuales por debajo del promedio del sistema (16.5%) y 5.63 puntos "
            "por debajo de la banca mediana (17.2%).")
    assert deterministic_direction_errors(ctx, text) == []


def test_second_marker_still_judged_when_actually_wrong():
    """El corte por marcador no debe volverse ciego: si la afirmación del SEGUNDO marcador
    es falsa, se marca igual."""
    ctx = {"indicators": {"morosidad": {"raw": 1.67}},
           "benchmarks": {"peer_groups": {"large_banks": {"npl_avg": 1.5}}}}
    text = ("La mora de 1.67% supera el umbral interno de 1.2% y se sitúa por debajo del "
            "promedio de pares grandes (1.5%).")
    flags = deterministic_direction_errors(ctx, text)
    assert any("morosidad" in f for f in flags), flags


def test_wrapped_sentence_across_lines_is_still_checked():
    """El texto renderizado envuelve la oración en varias líneas; cortar por '\\n' dejaba el
    sujeto y la referencia en fragmentos distintos y el error se escapaba."""
    text = ("La tasa de mora (1.67%) se sitúa por debajo del umbral de alerta\n"
            "regulatoria y del promedio del grupo de bancos grandes (1.5%), con el\n"
            "98.25% de la cartera en la categoría de menor riesgo.")
    assert deterministic_direction_errors(_bank_ctx(), text)


# ── Superlativo transversal: ahora también banca y seguros ────────────────────
#
# Hallazgos del Deep Dive de banca (2026-08-06). El patrón 8 existía pero era LETRA MUERTA
# fuera de pensiones: sólo `pension_intel` inyectaba `posiciones_dimension`, y su léxico y
# sus sinónimos de dimensión eran del vocabulario de AFP.

def _banca_pos():
    return {"posiciones_dimension": {
        "Solidez Financiera": {"rank": 1, "n": 16, "es_lider": True,
                               "lider": "Banco Popular Dominicano", "lider_score": 100.0},
        "Liquidez": {"rank": 12, "n": 16, "es_lider": False,
                     "lider": "BDI", "lider_score": 88.0},
    }}


def test_superlativo_de_banca_en_dimension_que_no_lidera():
    """Ámbito 'de la banca múltiple' — antes el regex sólo reconocía 'del sistema/de las AFP'."""
    txt = "Su liquidez es la más alta de la banca múltiple."
    flags = deterministic_direction_errors  # noqa: F841 — evita import no usado en el módulo
    out = deterministic_unsupported(_banca_pos(), txt)
    assert any("Liquidez" in f for f in out), out


def test_sin_precedente_es_un_salto_de_alcance_temporal():
    """El hallazgo #3: percentil 100 dice 'el mejor de la muestra ACTUAL', no 'nunca visto'."""
    txt = "Presenta una capacidad de liquidez sin precedente en el sistema."
    out = deterministic_unsupported(_banca_pos(), txt)
    assert any("Liquidez" in f for f in out), out


def test_superlativo_valido_en_la_dimension_que_si_lidera():
    """Popular SÍ lidera solidez (100/100, percentil 100): la afirmación es cierta."""
    txt = "Registra la solvencia más alta del sistema."
    out = deterministic_unsupported(_banca_pos(), txt)
    assert not any("Solidez" in f for f in out), out


def test_lider_generico_en_el_mensaje():
    """El campo transversal es `lider`; `lider_afp` sigue funcionando para pensiones."""
    out = deterministic_unsupported(_banca_pos(), "La liquidez más alta del sistema.")
    assert any("BDI" in f for f in out), out
    legacy = {"posiciones_dimension": {"Escala (AUM)": {
        "rank": 2, "n": 7, "es_lider": False, "lider_afp": "AFP Popular"}}}
    out2 = deterministic_unsupported(legacy, "Tiene la mayor escala del sistema.")
    assert any("AFP Popular" in f for f in out2), out2


def test_sin_posiciones_no_se_juzga_superlativo():
    """Best-effort: sin el dato no se inventa un veredicto."""
    assert deterministic_unsupported({}, "Es el mayor del sistema en liquidez.") == []
