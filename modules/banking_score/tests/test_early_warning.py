"""Tests de las reglas PURAS del motor de alerta temprana (sin DB)."""
from modules.banking_score.early_warning import (
    Alert,
    classify_profile,
    ensemble_score,
    evaluate,
    format_alerts_text,
    percentile,
    rule_capital_erosion,
    rule_concentration,
    rule_coverage,
    rule_funding,
    rule_growth,
    rule_liquidity,
    rule_morosidad,
    rule_morosidad_nivel,
    rule_solvency,
)


def test_percentile_interpola():
    assert percentile([10, 20, 30, 40], 0.90) == 37.0
    assert percentile([], 0.5) is None
    assert percentile([5], 0.9) == 5


def test_growth_solo_si_supera_pares_y_piso():
    assert rule_growth(0.40, 0.30) is not None            # > p90 y > 25%
    assert rule_growth(0.20, 0.10) is None                # no supera el piso 25%
    assert rule_growth(0.28, 0.35) is None                # no supera p90
    assert rule_growth(None, 0.3) is None


def test_funding_sobre_p90():
    assert rule_funding(8.0, 6.0) is not None
    assert rule_funding(5.0, 6.0) is None


def test_coverage_severidad():
    assert rule_coverage(120) is None
    assert rule_coverage(80).severity == "media"          # < 100
    assert rule_coverage(50).severity == "alta"           # < 60


def test_morosidad_dispara_por_multiplo_o_pp():
    assert rule_morosidad(6.0, 3.0) is not None            # 2× (≥1.5×)
    assert rule_morosidad(5.0, 3.0) is not None            # +2pp
    assert rule_morosidad(3.5, 3.0) is None                # ni ×1.5 ni +2pp


def test_solvency_cerca_del_piso():
    assert rule_solvency(15) is None
    assert rule_solvency(11.5).severity == "media"         # < 12
    assert rule_solvency(10.2).severity == "alta"          # < 10.5


def test_liquidity_por_fuga_o_piso():
    assert rule_liquidity(20.0, -0.15).severity == "alta"  # fuga de depósitos
    assert rule_liquidity(10.0, 0.0).severity == "media"   # bajo el piso de liquidez
    assert rule_liquidity(20.0, 0.0) is None


def test_concentration():
    assert rule_concentration(35) is not None
    assert rule_concentration(25) is None


def test_concentration_encuadre_consciente_de_naturaleza():
    """La bandera dispara igual, pero el encuadre cambia según la naturaleza de la entidad:
    banca privada → proxy de vinculados/fraude; banca estatal → concentración estructural."""
    privada = rule_concentration(47.2, is_state_owned=False)
    estatal = rule_concentration(47.2, is_state_owned=True)
    # ambas disparan, misma severidad y valor
    assert privada.code == estatal.code == "concentracion"
    assert privada.severity == estatal.severity == "media"
    assert privada.value == estatal.value == 47.2
    # el encuadre difiere: privada invoca el fraude; estatal NO, lo lee como estructural
    assert "fraude" in privada.basis and "vinculados" in privada.basis
    assert "estructural" in estatal.basis and "mandato" in estatal.basis
    assert "fraude" not in estatal.basis


def test_morosidad_nivel_umbral_relativo_por_tipo():
    """El nivel de morosidad se juzga contra un umbral RELATIVO al tipo: la misma mora que
    alarma en un banco múltiple es normal en una corporación de crédito."""
    # 10% de mora: sobre el umbral del banco múltiple (5%), normal para corporación (15%)
    assert rule_morosidad_nivel(10.0, "banca_multiple") is not None
    assert rule_morosidad_nivel(10.0, "corporacion_credito") is None
    # severidad alta al duplicar el umbral del tipo
    assert rule_morosidad_nivel(11.0, "banca_multiple").severity == "alta"     # ≥ 2×5
    assert rule_morosidad_nivel(7.0, "banca_multiple").severity == "media"
    # tipo desconocido → piso por defecto; None si no hay dato
    assert rule_morosidad_nivel(8.0, None) is not None                         # > 7.0 default
    assert rule_morosidad_nivel(None, "banca_multiple") is None


def test_capital_erosion_es_cambio_no_nivel():
    """La erosión mira la CAÍDA del capital, no su nivel — un banco grande con capital
    estructuralmente bajo pero estable NO dispara (lección de la bandera revertida #598)."""
    assert rule_capital_erosion(8.0, 8.2) is None                    # nivel bajo pero estable
    assert rule_capital_erosion(9.0, 11.0).severity == "media"       # cae 2pp
    assert rule_capital_erosion(7.0, 11.0).severity == "alta"        # cae 4pp
    assert rule_capital_erosion(12.0, 11.0) is None                  # sube
    assert rule_capital_erosion(None, 11.0) is None


def test_ensemble_score_pondera_y_ordena():
    """El puntaje del conjunto suma pesos calibrados; una 'alta' pesa más; ordena por peso."""
    vacio = ensemble_score([])
    assert vacio["score"] == 0.0 and vacio["band"] == "baja" and vacio["contributors"] == []
    alerts = [
        Alert("morosidad_nivel", "Morosidad sobre el umbral de su tipo", "alta", 12.0, 5.0, "", "%"),
        Alert("estres_liquidez", "Estrés de liquidez", "media", -12.0, -10.0, "", "%"),
    ]
    res = ensemble_score(alerts)
    assert 0 < res["score"] <= 100
    # morosidad_nivel (0.38) domina sobre estres_liquidez (0.02)
    assert res["contributors"][0]["code"] == "morosidad_nivel"


def test_sin_señales_encendidas_el_cero_es_verdadero():
    """Ninguna bandera activa ⇒ presión cero. Acá el 0.0 SÍ es una medición."""
    vacio = ensemble_score([])
    assert vacio["score"] == 0.0 and vacio["band"] == "baja"
    assert vacio["contributors"] == [] and vacio["scorable"] is True


def test_solo_señales_sin_peso_NO_es_cero_es_no_puntuable():
    """El cero fabricado. Una entidad cuya única bandera activa no tiene peso calibrado
    —concentración top-10, que no es reconstruible del histórico contable— NO tiene presión
    cero: no tiene medición. Publicarlo como '0.0/100 (banda baja)' ponía un all-clear encima
    de una bandera activa, y el mismo informe la llamaba tres renglones abajo vulnerabilidad
    estructural. Un dato ausente es None, jamás 0.0."""
    solo_contexto = ensemble_score([Alert("concentracion", "x", "media", 40.0, 30.0, "", "%")])
    assert solo_contexto["score"] is None, "no puntuable no es cero"
    assert solo_contexto["band"] is None
    assert solo_contexto["contributors"] == []
    assert solo_contexto["scorable"] is False
    assert solo_contexto["reason"]


def test_el_texto_declara_la_brecha_y_no_imprime_indice():
    """La superficie que lee el comité: sin score, el bloque declara el motivo y afirma que
    la bandera sigue vigente — nunca un número."""
    from dataclasses import asdict

    from modules.banking_score.early_warning import format_alerts_text
    alerta = Alert("concentracion", "Concentración elevada (top-10)", "media", 50.9, 30.0,
                   "base", "top-10 / cartera total %")
    txt = format_alerts_text({"alerts": [asdict(alerta)], "score": None, "band": None,
                              "perfil": None})
    assert "no puntuable" in txt
    assert "0.0/100" not in txt and "banda baja" not in txt
    assert "sigue vigente" in txt, "debe decir que la bandera no se cae, solo no se pondera"
    assert "50.9" in txt, "la bandera y su cifra se siguen publicando"


def test_concentracion_extrema_escala_a_alta():
    """Era la única de las nueve reglas sin tramo 'alta': un 50.9% pesaba igual que un 30.1%.
    Como esta bandera no tiene peso en el conjunto, la severidad es su único ordenamiento."""
    from modules.banking_score.early_warning import CONCENTRATION, rule_concentration
    assert rule_concentration(CONCENTRATION + 0.1).severity == "media"
    assert rule_concentration(2 * CONCENTRATION + 0.1).severity == "alta"


def test_la_glosa_nombra_el_denominador_que_realmente_se_divide():
    """`concentracion_top10_pct` divide por `cartera_total`; la glosa decía 'cartera bruta'
    —la etiqueta vieja, sobreviviente del fix que unificó el cálculo—. El informe publicaba
    un denominador que no era el que se dividía."""
    from modules.banking_score.early_warning import rule_concentration
    assert rule_concentration(50.9).metric == "top-10 / cartera total %"


def test_classify_profile_agudo_vs_cronico():
    """Distingue el deterioro agudo (sano→enfermo) del zombi crónico (podrido hace 2 años)."""
    jump = [Alert("salto_morosidad", "Salto de morosidad", "alta", 12.0, 3.0, "", "%")]
    # sano hace 2 años + salto ahora → agudo
    agudo = {"bank_type": "banca_multiple", "morosidad_pct": 12.0, "morosidad_chronic": 3.0}
    assert classify_profile(agudo, jump) == "agudo"
    # ya enfermo hace 2 años, sin señal de cambio → crónico (zombi)
    cronico = {"bank_type": "banca_multiple", "morosidad_pct": 12.0, "morosidad_chronic": 11.0}
    assert classify_profile(cronico, []) == "cronico"
    # enfermo hace 2 años PERO con salto vigente → sigue siendo agudo (se deteriora más)
    assert classify_profile(cronico, jump) == "agudo"
    # morosidad bajo el umbral de su tipo → nada que clasificar
    sano = {"bank_type": "banca_multiple", "morosidad_pct": 3.0, "morosidad_chronic": 2.0}
    assert classify_profile(sano, []) is None


def test_format_incluye_indice_y_perfil():
    block = {"alerts": [{"label": "Morosidad sobre el umbral de su tipo", "severity": "alta",
                         "value": 12.0, "threshold": 5.0, "basis": "x", "metric": "morosidad %"}],
             "score": 61.0, "band": "alta", "perfil": "agudo"}
    txt = format_alerts_text(block)
    assert "Índice de presión de deterioro" in txt and "61.0/100" in txt
    assert "deterioro agudo" in txt


def test_evaluate_ordena_alta_primero():
    m = {"solvencia_pct": 10.2, "cobertura_pct": 80, "concentracion_top10_deudores_pct": 40}
    peers = {"growth_p90": None, "funding_p90": None}
    alerts = evaluate(m, peers)
    codes = [a.code for a in alerts]
    assert "solvencia_piso" in codes and "brecha_provisiones" in codes and "concentracion" in codes
    assert alerts[0].severity == "alta"                    # la 'alta' va primero


def test_format_alerts_text_vacio_y_con_alertas():
    empty = format_alerts_text({"alerts": []})
    assert "Sin banderas" in empty and "no detecta fraude" in empty
    txt = format_alerts_text({"alerts": [
        {"label": "Salto de morosidad", "severity": "alta", "value": 4.83,
         "threshold": 3.0, "basis": "Deterioro diferido", "metric": "morosidad %"},
    ]})
    assert "**Salto de morosidad**" in txt and "4.83" in txt and "umbral 3.0" in txt
