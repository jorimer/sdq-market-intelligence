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
    """El puntaje del conjunto suma pesos calibrados; una 'alta' pesa más; ordena por peso.
    Polaridad INVERTIDA: 100 = ningún precursor activo, igual que todo otro 0-100 del informe."""
    vacio = ensemble_score([])
    assert vacio["salud_precursores"] == 100.0 and vacio["contributors"] == []
    alerts = [
        Alert("morosidad_nivel", "Morosidad sobre el umbral de su tipo", "alta", 12.0, 5.0, "", "%"),
        Alert("estres_liquidez", "Estrés de liquidez", "media", -12.0, -10.0, "", "%"),
    ]
    res = ensemble_score(alerts)
    assert 0 <= res["salud_precursores"] < 100, "con precursores activos la salud BAJA"
    # El orden se DIO VUELTA al derivar los pesos de la evidencia: estres_liquidez (0.364)
    # pasa a pesar más que morosidad_nivel (0.312). Antes valía 0.02 con la glosa "confirma
    # tarde, no anticipa"; sale material en las diez especificaciones medidas.
    assert res["contributors"][0]["code"] == "estres_liquidez"


def test_el_indice_reporta_las_banderas_que_NO_cubre():
    """El índice pondera siete de las nueve reglas. Las activas que quedan afuera viajan con
    el score para que ninguna superficie pueda mostrar el número sin mostrar lo que no cubre."""
    solo_contexto = ensemble_score([Alert("concentracion", "x", "media", 40.0, 30.0, "", "%")])
    assert solo_contexto["salud_precursores"] == 100.0, (
        "sobre el dominio calibrado el resultado es VERDADERO: ninguno de los siete "
        "precursores está activo. Suprimirlo tiraba una medición cierta")
    assert solo_contexto["contributors"] == []
    assert [u["code"] for u in solo_contexto["uncalibrated"]] == ["concentracion"]
    assert solo_contexto["n_calibradas"] == 7


def test_una_bandera_con_peso_no_aparece_como_fuera_del_indice():
    res = ensemble_score([Alert("morosidad_nivel", "x", "alta", 12.0, 5.0, "", "%")])
    assert res["uncalibrated"] == [] and res["salud_precursores"] < 100


def test_el_encabezado_declara_QUE_mide_el_indice():
    """El defecto no era el número: era el rótulo. 'presión del conjunto: 0.0/100 (banda
    baja)' prometía cubrir las nueve reglas y se leía como all-clear encima de una bandera
    activa. Ahora nombra su dominio y afirma el cero como resultado."""
    from dataclasses import asdict

    from modules.banking_score.early_warning import format_alerts_text
    alerta = Alert("concentracion", "Concentración elevada (top-10)", "media", 50.9, 30.0,
                   "base", "top-10 / cartera total %")
    txt = format_alerts_text({"alerts": [asdict(alerta)],
                              "ensemble": ensemble_score([alerta]),
                              "score": 0.0, "band": "baja", "perfil": None})
    assert "señales de deterioro temprano" in txt, "el encabezado debe decir QUÉ mide"
    assert "del conjunto" not in txt, "no puede prometer cobertura que no tiene"
    assert "ninguna encendida" in txt, "el resultado se afirma, no se deja como banda"
    assert "banda baja" not in txt
    assert "fuera del índice" in txt, "la bandera no cubierta se marca en su línea"
    assert "50.9%" in txt, "la cifra sale con su unidad, no pelada"


def test_el_texto_no_explica_la_metodologia_en_medio_del_analisis():
    """La sección informa riesgo; el porqué metodológico vive en Limitaciones. Una versión
    previa de este arreglo puso dos párrafos sobre nuestros propios límites acá, y convirtió
    la sección en una excusa: más palabras y ninguna señal nueva para el comité."""
    from dataclasses import asdict

    from modules.banking_score.early_warning import format_alerts_text
    alerta = Alert("concentracion", "Concentración elevada (top-10)", "media", 50.9, 30.0,
                   "base", "top-10 / cartera total %")
    txt = format_alerts_text({"alerts": [asdict(alerta)],
                              "ensemble": ensemble_score([alerta]),
                              "score": 0.0, "band": "baja", "perfil": None})
    for excusa in ("no es reconstruible", "divulgación de supervisión", "registro contable",
                   "está en curso", "ausencia de una medición"):
        assert excusa not in txt, f"«{excusa}» es metodología: va a Limitaciones, no acá"
    assert len(txt.split("\n\n")) <= 3, "encabezado + intro + banderas; sin ensayo"


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
    assert "señales de deterioro temprano" in txt and "61.0/100" in txt
    assert "presión de deterioro" not in txt, (
        "polaridad invertida: en este documento cada otro 0-100 es «más es mejor», y este era "
        "el único al revés — el original decía «0.0/100 (banda baja)», con el número gritando "
        "lo peor y el paréntesis diciendo lo contrario")
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
    # La cifra sale con su UNIDAD y el umbral con su SIGNIFICADO: "value: 4.83 (umbral 3.0)"
    # era notación de motor, no una frase que alguien lea en un comité.
    assert "**Salto de morosidad**" in txt and "4.83%" in txt and "3%" in txt
    assert "4.83 " not in txt, "el número pelado, sin unidad, no se publica"


# ── Panel de márgenes: la lectura temprana cuando NADA se enciende ──

def test_el_panel_cubre_las_siete_calibradas_y_solo_esas():
    from modules.banking_score.early_warning import ALERT_WEIGHTS, signal_panel
    p = signal_panel({}, {})
    assert {s["code"] for s in p} == set(ALERT_WEIGHTS), (
        "el panel es el DOMINIO del índice: ni una señal calibrada de menos, ni una de fuera")


def test_el_panel_distingue_sana_de_no_evaluable():
    """`rule_*` devuelve None tanto si la entidad está sana como si falta el input, y las dos
    quedaban invisibles. Una regla sin su dato no falla: DESAPARECE."""
    from modules.banking_score.early_warning import signal_panel
    sana = {"morosidad_pct": 1.5, "bank_type": "banca_multiple"}
    p = {s["code"]: s for s in signal_panel(sana, {})}
    assert p["morosidad_nivel"]["estado"] == "sin_activar"
    assert p["morosidad_nivel"]["margen"] == 3.5          # 5.0 − 1.5
    assert p["solvencia_piso"]["estado"] == "sin_dato", "sin solvencia no se inventa un margen"
    assert p["solvencia_piso"]["value"] is None


def test_el_margen_es_positivo_del_lado_sano_en_ambas_direcciones():
    """El lector compara márgenes entre señales; que unas se disparen por arriba y otras por
    abajo no puede cambiarle el signo."""
    from modules.banking_score.early_warning import signal_panel
    m = {"morosidad_pct": 1.5, "cobertura_pct": 200.6, "solvencia_pct": 15.37,
         "bank_type": "banca_multiple"}
    p = {s["code"]: s for s in signal_panel(m, {})}
    assert p["morosidad_nivel"]["margen"] > 0       # peor es MAYOR
    assert p["brecha_provisiones"]["margen"] > 0    # peor es MENOR
    assert p["solvencia_piso"]["margen"] > 0        # peor es MENOR


def test_el_panel_y_las_reglas_coinciden_EN_LAS_DOS_DIRECCIONES():
    """Anti-deriva. La versión anterior solo comprobaba que el panel no marcara de más, y el
    fallo real fue el contrario: la regla encendía `salto_morosidad` y el panel decía "sin
    activar" —usaba `max` de las dos condiciones cuando la regla dispara con cualquiera—.
    El informe salió contradiciéndose: "no presenta precursores activos" con la bandera
    listada tres renglones abajo. Un guard que mira un solo lado deja pasar la mitad."""
    from modules.banking_score.early_warning import ALERT_WEIGHTS, evaluate, signal_panel
    casos = [
        {"morosidad_pct": 12.0, "cobertura_pct": 50.0, "solvencia_pct": 9.0,
         "bank_type": "banca_multiple"},
        # el caso real de producción: mora 0.93 → 1.56 dispara por ×1.5 y no por +2 puntos
        {"morosidad_pct": 1.56, "morosidad_prev4": 0.93, "cobertura_pct": 200.0,
         "solvencia_pct": 17.0, "capital_now": 17.0, "capital_prior": 16.0,
         "bank_type": "banca_multiple"},
        {"morosidad_pct": 3.0, "morosidad_prev4": 1.0, "cobertura_pct": 90.0,
         "solvencia_pct": 11.0, "bank_type": "banca_multiple"},
    ]
    for m in casos:
        panel = {s["code"] for s in signal_panel(m, {}) if s["estado"] == "activa"}
        regla = {a.code for a in evaluate(m, {})} & set(ALERT_WEIGHTS)
        assert panel == regla, (
            f"panel y reglas discrepan para {m}: panel={sorted(panel)} regla={sorted(regla)}")


def test_solo_se_rankea_lo_comparable_convergentes_en_trimestres():
    """Ordenar márgenes crudos entre sí era ilegítimo: 1,47 puntos de variación del
    apalancamiento y 100,6 de cobertura no están en la misma escala. El único superlativo es
    entre los que CONVERGEN, y en trimestres — unidad común a todos."""
    from modules.banking_score.early_warning import panel_relations, signal_panel
    m = {"bank_type": "banca_multiple", "morosidad_pct": 1.53, "morosidad_prev4": 1.62,
         "cobertura_pct": 200.6, "cobertura_prev4": 286.0,
         "solvencia_pct": 15.37, "solvencia_prev4": 14.9}
    r = panel_relations(signal_panel(m, {}))
    assert r["n_activos"] == 0
    assert r["converge_primero"]["label"] == "Brecha de provisiones", (
        "la cobertura es la única que va hacia su umbral")
    assert r["n_convergen"] == 1
    assert r["converge_primero"]["trimestres_al_umbral"] > 0
    assert "margen_mas_ajustado" not in r, "el superlativo por margen crudo no debe existir"


def test_una_tasa_no_recibe_plazo_al_umbral():
    """`erosion_capital`, `salto_morosidad` y `crecimiento_anomalo` YA son variaciones.
    Extrapolar una tasa linealmente no significa nada, así que no llevan ETA."""
    from modules.banking_score.early_warning import signal_panel
    m = {"bank_type": "banca_multiple", "capital_now": 15.37, "capital_prior": 14.9,
         "morosidad_pct": 1.53, "morosidad_prev4": 1.62, "assets_yoy": 0.08}
    p = {s["code"]: s for s in signal_panel(m, {"growth_p90": 0.19})}
    for code in ("erosion_capital", "salto_morosidad", "crecimiento_anomalo"):
        assert p[code]["trimestres_al_umbral"] is None


def test_el_plazo_se_escribe_condicional_sin_rotulo_de_salvedad():
    """La salvedad va en la gramática. Un «lectura mecánica, no proyección» entre paréntesis
    le avisa al lector que desconfíe de la frase que acaba de leer."""
    from modules.banking_score.early_warning import _prosa_margenes, signal_panel
    m = {"bank_type": "banca_multiple", "morosidad_pct": 1.53, "morosidad_prev4": 1.62,
         "cobertura_pct": 200.6, "cobertura_prev4": 286.0}
    txt = _prosa_margenes(signal_panel(m, {}))
    assert "De sostenerse el ritmo" in txt
    for rotulo in ("no proyección", "lectura mecánica", "extrapolación", "meramente"):
        assert rotulo not in txt.lower()


def test_sin_banderas_el_texto_igual_muestra_los_margenes():
    """El caso que motivó todo: 'ninguna señal activa' no informa nada sin el colchón de cada
    una. Un banco a 0.3 pp del piso y otro a 8 pp no están en la misma situación."""
    from modules.banking_score.early_warning import format_alerts_text, signal_panel
    m = {"morosidad_pct": 1.53, "cobertura_pct": 200.6, "solvencia_pct": 15.37,
         "bank_type": "banca_multiple"}
    txt = format_alerts_text({"alerts": [], "panel": signal_panel(m, {})})
    assert "Sin banderas" in txt
    assert "señales de deterioro temprano" in txt or "Sin dato para evaluar" in txt


def test_el_panel_llega_al_contexto_del_modelo():
    """Un cableado sin test DESAPARECE: si alguien saca el panel del contexto, el párrafo
    vuelve a hablar solo de las banderas encendidas y un informe sin alertas deja de decir a
    qué distancia está la entidad de cada umbral — sin que falle nada."""
    import pathlib
    src = (pathlib.Path(__file__).resolve().parents[1] / "products.py").read_text(encoding="utf-8")
    assert '"panel_precursores"' in src, "el panel debe viajar al contexto de la narrativa"
    assert '"relaciones_computadas"' in src, (
        "los superlativos y el orden se COMPUTAN y el modelo los copia; sin ellos los deduce "
        "del panel y falla las relaciones")


def test_la_explicacion_metodologica_vive_en_limitaciones():
    """El porqué de que la concentración quede fuera del índice va en Limitaciones, no en el
    medio del análisis de riesgo."""
    from modules.banking_score.products import _LIMITATIONS_TEXT
    assert "diez mayores deudores" in _LIMITATIONS_TEXT
    assert "siete precursores calibrados" in _LIMITATIONS_TEXT
    assert "no se les asigna un peso que el dato no respalde" in _LIMITATIONS_TEXT


def test_el_modelo_no_recibe_numeros_crudos():
    """Al verificar en prod, el modelo escribió "2.3 veces" y "50.9%" junto al "2,3" del
    bloque determinista: dos notaciones decimales en el mismo párrafo. La cura no es una regla
    más en el prompt —es no darle el número crudo—."""
    from modules.banking_score.early_warning import (
        panel_para_modelo, relaciones_para_modelo, signal_panel)
    m = {"bank_type": "banca_multiple", "morosidad_pct": 1.53, "morosidad_prev4": 1.24,
         "cobertura_pct": 200.6, "cobertura_prev4": 229.67}
    panel = signal_panel(m, {})
    crudos = {"value", "threshold", "margen", "velocidad_4t", "trimestres_al_umbral"}
    for fila in panel_para_modelo(panel):
        assert not (crudos & set(fila)), f"campo crudo servido al modelo: {crudos & set(fila)}"
    rel = relaciones_para_modelo(panel)
    assert not (crudos & set(rel["converge_primero"] or {}))
    assert rel["converge_primero"]["valor"] == "2.0 veces"
    assert rel["converge_primero"]["horizonte_al_umbral"].startswith("alrededor de")


def test_con_narrativa_el_bloque_no_repite_los_margenes():
    """La sección decía lo mismo dos veces: el párrafo del modelo y el determinista narraban
    ambos la cobertura. Con narrativa, el determinista se queda solo con los hechos."""
    from modules.banking_score.early_warning import format_alerts_text, signal_panel
    m = {"bank_type": "banca_multiple", "morosidad_pct": 1.53, "morosidad_prev4": 1.24,
         "cobertura_pct": 200.6, "cobertura_prev4": 229.67}
    panel = signal_panel(m, {})
    base = {"alerts": [], "panel": panel}
    assert "La que más se movió" in format_alerts_text(base)
    assert "La que más se movió" not in format_alerts_text({**base, "con_narrativa": True})


def test_el_separador_decimal_es_el_del_informe():
    """RD usa PUNTO decimal, y el resto del Deep Dive también —medido en producción: 133
    cifras con punto contra 8 con coma—. Una versión previa usó coma acá y dejó la §Alerta
    Temprana como la única sección fuera de convención, con "2,3 veces" del bloque
    determinista y "2.3 veces" del modelo en el mismo párrafo."""
    from modules.banking_score.early_warning import _expresar, _horizonte
    assert _expresar(200.6, "veces") == "2.0 veces"
    assert _expresar(15.37, "pct") == "15.37%"
    assert _expresar(50.8989, "pct") == "50.9%"
    assert "," not in _horizonte(13.8)


def test_los_pesos_suman_uno_y_crecimiento_esta_en_cero():
    """El peso de crecimiento_anomalo NO es un olvido: da cero en las diez especificaciones
    medidas. Se deja en el dict —en vez de borrarlo— porque "se midió y no predice" es una
    afirmación distinta, y más fuerte, que "no se pudo medir"."""
    from modules.banking_score.early_warning import ALERT_WEIGHTS
    assert abs(sum(ALERT_WEIGHTS.values()) - 1.0) < 1e-6
    assert ALERT_WEIGHTS["crecimiento_anomalo"] == 0.0
    assert ALERT_WEIGHTS["estres_liquidez"] > ALERT_WEIGHTS["morosidad_nivel"], (
        "la evidencia invierte el orden que tenía la calibración sin artefacto")


def test_un_precursor_medido_en_cero_NO_es_lo_mismo_que_uno_sin_medir():
    """Distinción que el índice debe preservar: crecimiento está EN el dominio calibrado con
    peso cero; concentración y fondeo están FUERA porque no se pudieron medir contra quiebras."""
    from modules.banking_score.early_warning import ALERT_WEIGHTS
    assert "crecimiento_anomalo" in ALERT_WEIGHTS
    assert "concentracion" not in ALERT_WEIGHTS and "fondeo_caro" not in ALERT_WEIGHTS
    res = ensemble_score([Alert("crecimiento_anomalo", "x", "media", 40.0, 25.0, "", "%")])
    assert res["uncalibrated"] == [], "crecimiento SÍ es calibrado; su peso medido es 0"
    assert res["salud_precursores"] == 100.0, "peso 0 ⇒ no mueve el índice"
