"""Alerta temprana bancaria — señales de MONITOREO ancladas a la crisis RD 2003.

El score puntual mide solidez sobre dato publicado; NO detecta fraude/contabilidad
paralela (autoevidente). Pero la literatura de la crisis (Panel de Expertos BCRD 2005,
Fitch 2003, Montas) identificó precursores que SÍ son detectables en el dato: expansión
agresiva, fondeo por encima del sistema, provisiones insuficientes, salto de morosidad,
solvencia erosionándose, fuga de depósitos y concentración. Este motor las evalúa por
banco al último período y las surfacea como ALERTAS A MONITOREAR — complemento del rating,
no un veredicto.

Reglas PURAS (sin DB) → unit-testables; ``compute_alerts`` arma el contexto (histórico del
banco + distribución de pares) y las evalúa. Umbrales calibrables (constantes abajo). Cada
alerta cita su lección de 2003 en ``basis``.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import date
from typing import Dict, List, Optional

from sqlalchemy.orm import Session

from modules.banking_score.scoring.engine import concentracion_top10_pct

# ── Umbrales (calibrables) ─────────────────────────────────────────────────────
GROWTH_ABS = 0.25          # crecimiento interanual mínimo para marcar (sanity floor)
COVERAGE_WARN = 100.0      # cobertura de provisiones % (Fitch: "100% coverage")
COVERAGE_HIGH = 60.0
MOROSIDAD_MULT = 1.5       # morosidad ≥ 1.5× su nivel de hace 4T
MOROSIDAD_PP = 2.0         # …o +2 puntos porcentuales
SOLV_WARN = 12.0           # solvencia % — cerca del piso regulatorio de 10%
SOLV_HIGH = 10.5
LIQ_FLOOR = 15.0           # (activos_líquidos/pasivos_exigibles)×100
DEPOSIT_DROP = -0.10       # caída trimestral de depósitos ≥ 10% (proxy de corrida)
CONCENTRATION = 30.0       # top-10 / cartera total %  (proxy de vinculados)

# ── Calibración del CONJUNTO ponderado ─────────────────────────────────────────
# ⚠ PROCEDENCIA EN REVISIÓN — estos siete pesos NO tienen artefacto que los respalde.
# Se documentaron como "calibrados sobre la cohorte de 35 terminaciones agudas del histórico
# SIB, regresión logística estandarizada validada leave-one-entity-out (AUC 0.88, detección
# 34/35, falsos positivos 1/45)". Esa calibración nunca existió como código: ni cohorte
# definida, ni matriz, ni script. Solo la prosa.
#
# `validation/ew_calibration.py` es ahora ESE artefacto, y al reconstruirlo encontró que los
# pesos no están identificados por el dato: la receta de cohorte los mueve tanto como el dato
# (morosidad_nivel entre 0.00 y 0.42; brecha_provisiones entre 0.00 y 0.55). Dos discrepancias
# son robustas a las seis recetas probadas:
#   • crecimiento_anomalo (0.08 acá) recibe peso CERO en todas — el histórico no sostiene que
#     el boom de crédito sea "la señal más temprana";
#   • estres_liquidez (0.02 acá) sale siempre material, entre 0.19 y 0.69 — un orden de
#     magnitud, y en dirección contraria a la glosa de que "confirma tarde, no anticipa".
# El AUC leave-one-entity-out no llega a 0.88 en ninguna receta: el techo medido es 0.800.
#
# Los valores se dejan INTACTOS a propósito: cambiarlos mueve el índice de informes ya
# vendidos, y elegir la receta canónica es una decisión de metodología del dueño, no de
# implementación. Corré `sensitivity_table()` antes de tocarlos.
# Límite: solvencia_piso (0.06) no es verificable con esta fuente — Basilea es regulatoria y
# no existe pre-2004.
ALERT_WEIGHTS: Dict[str, float] = {
    "morosidad_nivel": 0.38,
    "brecha_provisiones": 0.20,
    "erosion_capital": 0.14,
    "salto_morosidad": 0.11,
    "crecimiento_anomalo": 0.08,
    "solvencia_piso": 0.06,
    "estres_liquidez": 0.02,
    # concentracion / fondeo_caro: contexto de monitoreo; sin peso predictivo confiable en el
    # histórico contable (top-10 y fondeo YTD no son reconstruibles pre-2004).
}

# La prosa que se PUBLICA vive en constantes, no incrustada en un f-string: un literal
# partido por ancho de línea deja de existir en el fuente aunque el valor salga bien, y un
# test que lo busque ahí falla sin motivo (o pasa sin protegerte).
# El rótulo dice QUÉ mide el índice. Decir "del conjunto" prometía cubrir las nueve reglas
# cuando solo pondera siete, y con eso un 0.0 legítimo se leía como all-clear global.
ENSEMBLE_ENCABEZADO = "Salud frente a los precursores calibrados"
ENSEMBLE_COBERTURA = "{evaluables} de {calibradas} evaluables"
ENSEMBLE_NINGUNO_ACTIVO = "ninguno activo"
# La bandera que quedó fuera del índice se NOMBRA, no se explica. El porqué metodológico va
# a Limitaciones; acá el comité necesita el hecho, no nuestra epistemología.
ENSEMBLE_FUERA_DEL_INDICE = "fuera del índice"
# El margen a cada umbral ES la lectura temprana. Sin él, "ninguna señal activa" no
# distingue a un banco holgado de uno a un pelo del disparo — y los dos se veían igual.
PANEL_ENCABEZADO = "Distancia a cada umbral al corte — dónde está la entidad en cada precursor"
PANEL_SIN_DATO = "sin dato para evaluar"

# Umbral de morosidad RELATIVO al tipo de entidad: lo "normal" difiere por modelo de negocio
# (una corporación de crédito opera con mora de dos dígitos; un banco múltiple no). Un umbral
# plano marcaría en falso a las pequeñas y subreaccionaría en las grandes — la misma lección
# que la bandera de capital revertida (#598): los umbrales de balance dependen del TIPO.
MOROSIDAD_FLOOR_BY_TYPE: Dict[str, float] = {
    "banca_multiple": 5.0,
    "aap": 7.0,
    "banco_ahorro_credito": 9.0,
    "corporacion_credito": 15.0,
}
DEFAULT_MOROSIDAD_FLOOR = 7.0
CAPITAL_EROSION_WARN = -1.0   # caída de patrimonio/activos (pp en 12m) que enciende la señal
CAPITAL_EROSION_HIGH = -3.0
CHRONIC_LOOKBACK_Q = 8        # ~2 años atrás: si ya estaba enferma entonces → zombi, no deterioro nuevo

# Solo entidades CAPTADORAS DE DEPÓSITOS — los precursores de la crisis 2003 (fuga de
# depósitos, fondeo, provisiones, morosidad) aplican a la banca de intermediación, no a
# agentes de cambio (``cambiaria``) ni a fiduciarias (perfil off-balance distinto).
MONITORED_TYPES = ("banca_multiple", "aap", "banco_ahorro_credito", "corporacion_credito")


@dataclass(frozen=True)
class Alert:
    code: str
    label: str
    severity: str          # "alta" | "media"
    value: Optional[float]
    threshold: float
    basis: str             # la lección de 2003 que la ancla
    metric: str


def _pct(num: Optional[float], den: Optional[float]) -> Optional[float]:
    if num is None or not den:
        return None
    return num / den * 100.0


def _yoy(now: Optional[float], prior: Optional[float]) -> Optional[float]:
    if now is None or not prior:
        return None
    return now / prior - 1.0


def percentile(values: List[float], q: float) -> Optional[float]:
    """Percentil *q* (0..1) por interpolación lineal. None si no hay valores."""
    xs = sorted(v for v in values if v is not None)
    if not xs:
        return None
    if len(xs) == 1:
        return xs[0]
    pos = q * (len(xs) - 1)
    lo = int(pos)
    frac = pos - lo
    hi = min(lo + 1, len(xs) - 1)
    return xs[lo] + (xs[hi] - xs[lo]) * frac


# ── Reglas puras — cada una devuelve Alert o None ──────────────────────────────

def rule_growth(assets_yoy: Optional[float], peer_p90: Optional[float]) -> Optional[Alert]:
    if assets_yoy is None or peer_p90 is None:
        return None
    if assets_yoy > peer_p90 and assets_yoy > GROWTH_ABS:
        return Alert("crecimiento_anomalo", "Crecimiento anómalo de activos", "media",
                     round(assets_yoy * 100, 1), round(peer_p90 * 100, 1),
                     "Expansión agresiva por encima de su capacidad (Montas/Panel 2003)",
                     "activos_totales interanual %")
    return None


def rule_funding(funding_cost: Optional[float], peer_p90: Optional[float]) -> Optional[Alert]:
    if funding_cost is None or peer_p90 is None or funding_cost <= peer_p90:
        return None
    return Alert("fondeo_caro", "Fondeo por encima del sistema", "media",
                 round(funding_cost, 2), round(peer_p90, 2),
                 "Baninter pagaba tasas pasivas sobre el sistema desde 1999 (Panel §24)",
                 "gastos_financieros/depósitos %")


def rule_coverage(cobertura_pct: Optional[float]) -> Optional[Alert]:
    if cobertura_pct is None or cobertura_pct >= COVERAGE_WARN:
        return None
    sev = "alta" if cobertura_pct < COVERAGE_HIGH else "media"
    return Alert("brecha_provisiones", "Brecha de provisiones", sev,
                 round(cobertura_pct, 1), COVERAGE_WARN,
                 "Cobertura < 100% ocultó pérdidas; Baninter difería provisiones (Fitch/Panel §31)",
                 "cobertura de provisiones %")


def rule_morosidad(now: Optional[float], prior4: Optional[float]) -> Optional[Alert]:
    if now is None or prior4 is None:
        return None
    if now >= MOROSIDAD_MULT * prior4 or now - prior4 >= MOROSIDAD_PP:
        return Alert("salto_morosidad", "Salto de morosidad", "alta",
                     round(now, 2), round(prior4, 2),
                     "Deterioro de cartera diferido/oculto (Panel §31)",
                     "morosidad % vs. 4T atrás")
    return None


def rule_solvency(solvencia_pct: Optional[float]) -> Optional[Alert]:
    if solvencia_pct is None or solvencia_pct >= SOLV_WARN:
        return None
    sev = "alta" if solvencia_pct < SOLV_HIGH else "media"
    return Alert("solvencia_piso", "Solvencia cerca del piso", sev,
                 round(solvencia_pct, 2), SOLV_WARN,
                 "Erosión patrimonial hacia el piso regulatorio de 10%",
                 "solvencia %")


def rule_liquidity(liq_ratio: Optional[float], deposit_qoq: Optional[float]) -> Optional[Alert]:
    low = liq_ratio is not None and liq_ratio < LIQ_FLOOR
    run = deposit_qoq is not None and deposit_qoq <= DEPOSIT_DROP
    if not (low or run):
        return None
    val = round(deposit_qoq * 100, 1) if run else (round(liq_ratio, 1) if liq_ratio is not None else None)
    return Alert("estres_liquidez", "Estrés de liquidez / fuga de depósitos",
                 "alta" if run else "media", val,
                 DEPOSIT_DROP * 100 if run else LIQ_FLOOR,
                 "Corridas de depósitos y dependencia de redescuento (Panel §12)",
                 "caída trimestral de depósitos %" if run else "activos líquidos/pasivos exigibles %")


def rule_concentration(concentration_pct: Optional[float],
                       is_state_owned: bool = False) -> Optional[Alert]:
    if concentration_pct is None or concentration_pct <= CONCENTRATION:
        return None
    # El encuadre de la bandera es CONSCIENTE de la naturaleza de la entidad: en banca de
    # propiedad estatal la concentración top-10 es en parte ESTRUCTURAL (grandes deudores
    # públicos/sectoriales por mandato), no un proxy de préstamos vinculados. Encuadrarla como
    # precursor del fraude de 2003 (calibrado sobre la banca privada) es un error de categoría
    # que además fuerza a la narrativa a justificarlo al revés.
    basis = ("En banca de propiedad estatal la concentración top-10 refleja en parte exposición "
             "estructural a grandes deudores públicos/sectoriales por mandato; el foco de riesgo "
             "es la CALIDAD de esa cartera dirigida, no un patrón de préstamos vinculados"
             if is_state_owned else
             "Los préstamos vinculados fueron el mecanismo central del fraude (proxy visible)")
    # Escalón de severidad: era la ÚNICA de las nueve reglas sin tramo "alta", así que un
    # 50.9% —un 70% por encima del umbral— pesaba igual que un 30.1%. Y como esta bandera no
    # tiene peso en el conjunto, la severidad es su único canal de ordenamiento: sin escalón,
    # una concentración extrema queda indistinguible de una apenas sobre el umbral. Se usa
    # 2× el umbral, el mismo idioma que `rule_morosidad_nivel` (2× el piso de su tipo).
    sev = "alta" if concentration_pct >= 2 * CONCENTRATION else "media"
    return Alert("concentracion", "Concentración elevada (top-10)", sev,
                 round(concentration_pct, 1), CONCENTRATION, basis,
                 # El denominador es `cartera_total` (ver `concentracion_top10_pct`). La glosa
                 # decía "cartera bruta": es la etiqueta VIEJA, sobreviviente del fix que
                 # unificó el cálculo. El informe publicaba un denominador que no era el que
                 # se dividía — la misma familia que el sujeto que viaja con el número.
                 "top-10 / cartera total %")


def rule_morosidad_nivel(mora_pct: Optional[float],
                         bank_type: Optional[str] = None) -> Optional[Alert]:
    """Nivel de morosidad sobre el umbral RELATIVO a su tipo (la señal de mayor peso del
    conjunto, 0.38). Distinta del *salto*: captura el nivel podrido, no el cambio. El umbral
    depende del tipo porque lo 'normal' difiere por modelo de negocio (histórico SIB)."""
    if mora_pct is None:
        return None
    floor = MOROSIDAD_FLOOR_BY_TYPE.get(bank_type or "", DEFAULT_MOROSIDAD_FLOOR)
    if mora_pct <= floor:
        return None
    sev = "alta" if mora_pct >= 2 * floor else "media"
    return Alert("morosidad_nivel", "Morosidad sobre el umbral de su tipo", sev,
                 round(mora_pct, 2), round(floor, 1),
                 "Nivel de cartera vencida sobre lo normal para su tipo de entidad "
                 "(umbral relativo calibrado del histórico SIB)",
                 "morosidad %")


def rule_capital_erosion(capital_now: Optional[float],
                         capital_prior: Optional[float]) -> Optional[Alert]:
    """Erosión de capital: caída del ratio patrimonio/activos (o solvencia) en 12m. Es el
    CAMBIO, no el nivel — a diferencia de la bandera de nivel revertida (#598), que marcaba
    en falso a los bancos grandes sanos que corren apalancamiento estructuralmente bajo. El
    erosión sostenida del margen de capital sí precede a la quiebra (histórico SIB, peso 0.14)."""
    if capital_now is None or capital_prior is None:
        return None
    drop = capital_now - capital_prior
    if drop > CAPITAL_EROSION_WARN:
        return None
    sev = "alta" if drop <= CAPITAL_EROSION_HIGH else "media"
    return Alert("erosion_capital", "Erosión de capital", sev,
                 round(drop, 2), CAPITAL_EROSION_WARN,
                 "El margen de capital se erosiona antes de la quiebra; discrimina la caída, "
                 "no el nivel (histórico SIB)",
                 "Δ patrimonio/activos pp (12m)")


def signal_panel(m: Dict, peers: Dict) -> List[Dict]:
    """Dónde está la entidad en CADA precursor calibrado, se haya encendido o no.

    Una sección de alerta temprana cuyo resultado es "ninguna señal activa" no informa nada
    si no dice a qué distancia está la entidad de cada umbral. Ese margen ES la lectura
    temprana: un banco a 0.3 pp del piso de solvencia y otro a 8 pp no están en la misma
    situación, y hoy los dos se veían igual —sin bandera—.

    Además separa dos cosas que ``rule_*`` colapsa en el mismo ``None``: la entidad SANA
    (valor conocido, lejos del umbral) y la NO EVALUABLE (falta el input). La segunda es la
    interesante: una regla sin su dato no falla, desaparece.

    Solo los siete con peso calibrado — es el dominio del índice. Las otras dos se reportan
    aparte, marcadas como fuera de él.
    """
    floor = MOROSIDAD_FLOOR_BY_TYPE.get(m.get("bank_type") or "", DEFAULT_MOROSIDAD_FLOOR)
    mora, mora4 = m.get("morosidad_pct"), m.get("morosidad_prev4")
    salto_umbral = (max(MOROSIDAD_MULT * mora4, mora4 + MOROSIDAD_PP)
                    if mora4 is not None else None)
    cap_now, cap_prior = m.get("capital_now"), m.get("capital_prior")
    delta_cap = (cap_now - cap_prior) if (cap_now is not None and cap_prior is not None) else None
    yoy, p90 = m.get("assets_yoy"), peers.get("growth_p90")
    dep_qoq, liq = m.get("deposit_qoq"), m.get("liq_ratio")

    # (code, etiqueta, métrica, valor, umbral, peor_es_mayor, valor_4T_atrás)
    # El último campo separa dos naturalezas: los indicadores de NIVEL tienen un rezago y por
    # tanto velocidad y plazo al umbral; los que YA SON UNA TASA (una variación de 12m, un
    # crecimiento interanual) no —extrapolar una tasa linealmente no significa nada— y se
    # reportan con dirección pero sin plazo. Declararlo evita inventar un ETA donde no lo hay.
    specs = [
        ("morosidad_nivel", "Morosidad sobre el umbral de su tipo", "morosidad %",
         mora, floor, True, m.get("morosidad_prev4")),
        ("brecha_provisiones", "Brecha de provisiones", "cobertura de provisiones %",
         m.get("cobertura_pct"), COVERAGE_WARN, False, m.get("cobertura_prev4")),
        ("erosion_capital", "Erosión de capital", "Δ patrimonio/activos pp (12m)",
         delta_cap, CAPITAL_EROSION_WARN, False, None),
        ("salto_morosidad", "Salto de morosidad", "morosidad % vs. 4T atrás",
         mora, salto_umbral, True, None),
        ("crecimiento_anomalo", "Crecimiento anómalo de activos", "activos interanual %",
         None if yoy is None else yoy * 100,
         None if p90 is None else max(p90, GROWTH_ABS) * 100, True, None),
        ("solvencia_piso", "Solvencia cerca del piso", "solvencia %",
         m.get("solvencia_pct"), SOLV_WARN, False, m.get("solvencia_prev4")),
        ("estres_liquidez", "Estrés de liquidez / fuga de depósitos",
         "caída trimestral de depósitos %" if dep_qoq is not None
         else "activos líquidos/pasivos exigibles %",
         None if dep_qoq is None else dep_qoq * 100,
         DEPOSIT_DROP * 100 if dep_qoq is not None else LIQ_FLOOR, False, None),
    ]
    if dep_qoq is None:
        specs[-1] = ("estres_liquidez", "Estrés de liquidez / fuga de depósitos",
                     "activos líquidos/pasivos exigibles %", liq, LIQ_FLOOR, False,
                     m.get("liq_ratio_prev4"))

    out: List[Dict] = []
    for code, label, metric, valor, umbral, peor_mayor, prev4 in specs:
        if valor is None or umbral is None:
            out.append({"code": code, "label": label, "metric": metric, "value": None,
                        "threshold": umbral, "estado": "sin_dato", "margen": None,
                        "velocidad_4t": None, "direccion": None, "trimestres_al_umbral": None})
            continue
        activa = valor >= umbral if peor_mayor else valor <= umbral
        # Margen SIEMPRE positivo cuando la entidad está del lado sano, sin importar la
        # dirección del indicador: el lector compara márgenes entre señales, no signos.
        margen = (umbral - valor) if peor_mayor else (valor - umbral)
        # Velocidad = variación en 12m del NIVEL. `avance` es cuánto de esa variación va
        # HACIA el umbral (positivo = converge), lo que normaliza el signo igual que el margen.
        vel = (valor - prev4) if prev4 is not None else None
        avance = None if vel is None else (vel if peor_mayor else -vel)
        direccion = None
        trimestres = None
        if avance is not None:
            direccion = "converge" if avance > 0 else "se_aleja" if avance < 0 else "estable"
            if direccion == "converge" and margen > 0:
                # Trimestres al umbral SI el ritmo de los últimos 4T se sostiene. La condición
                # viaja en la redacción («de sostenerse el ritmo»), no en un rótulo de salvedad.
                trimestres = round(margen / (avance / 4.0), 1)
        out.append({"code": code, "label": label, "metric": metric,
                    "value": round(valor, 2), "threshold": round(umbral, 2),
                    "estado": "activa" if activa else "sin_activar",
                    "margen": round(margen, 2),
                    "velocidad_4t": None if vel is None else round(vel, 2),
                    "direccion": direccion, "trimestres_al_umbral": trimestres})
    return out


def panel_relations(panel: List[Dict]) -> Dict:
    """Las RELACIONES del panel, computadas — el modelo las COPIA, no las deriva.

    El superlativo se toma SOLO entre los precursores que convergen, y en TRIMESTRES. Ordenar
    los márgenes crudos entre sí era ilegítimo: 1,47 puntos de variación del apalancamiento y
    100,6 puntos de cobertura no están en la misma escala, y declarar cuál es "el más
    ajustado" afirmaba una comparabilidad inexistente. El tiempo al umbral sí es común a
    todos, y además es la pregunta que importa: ¿alguno se está acercando, y a qué ritmo?

    ``n_evaluables`` impide que el silencio se lea como salud: con el índice invertido,
    100/100 sin decir sobre cuántas señales se midió sería una afirmación de salud construida
    sobre datos que faltan.
    """
    medibles = [s for s in panel if s["estado"] != "sin_dato"]
    activos = [s for s in medibles if s["estado"] == "activa"]
    convergen = sorted((s for s in medibles if s["estado"] == "sin_activar"
                        and s.get("trimestres_al_umbral") is not None),
                       key=lambda s: s["trimestres_al_umbral"])
    se_alejan = [s for s in medibles
                 if s["estado"] == "sin_activar" and s.get("direccion") in ("se_aleja", "estable")]

    def _ref(s):
        # sujeto-ok: cada cifra viaja con el precursor que la produce en `label`; no es una
        # cuota sobre una población.
        return {"label": s["label"], "metric": s["metric"], "value": s["value"],
                "threshold": s["threshold"], "margen": s["margen"],
                "velocidad_4t": s.get("velocidad_4t"),
                "trimestres_al_umbral": s.get("trimestres_al_umbral")}

    return {
        "n_calibradas": len(panel),
        "n_evaluables": len(medibles),
        "n_activos": len(activos),
        "n_convergen": len(convergen),
        "n_se_alejan": len(se_alejan),
        "sin_dato": [s["label"] for s in panel if s["estado"] == "sin_dato"],
        # El único superlativo legítimo: el que llega antes, entre los que van hacia el umbral.
        "converge_primero": _ref(convergen[0]) if convergen else None,
        "convergen": [_ref(s) for s in convergen],
        "activos": [_ref(s) for s in activos],
    }


def ensemble_score(alerts: List[Alert]) -> Dict:
    """Puntaje del CONJUNTO ponderado (0..100): la alerta temprana como suma de señales con
    sus pesos calibrados, no como banderas sueltas. Una 'alta' cuenta 1.5× su peso base.

    El índice mide UN DOMINIO ACOTADO: los siete precursores con peso calibrado. No es el
    conjunto de las nueve reglas. Cuando solo se encienden señales sin peso —`concentracion`,
    `fondeo_caro`, que no son reconstruibles del histórico contable— el 0.0 NO es un dato
    ausente: es la afirmación verdadera y útil de que ninguno de los siete precursores está
    presente. Lo que faltaba era decir QUÉ cubre el índice y avisar que hay una bandera
    encendida fuera de él; publicarlo como "presión del conjunto: 0.0/100 (banda baja)"
    prometía una cobertura que el número no tenía, y callaba la señal activa.

    Por eso ``uncalibrated`` viaja con el score: el consumidor no puede renderizar el índice
    sin ver lo que quedó afuera.
    """
    max_possible = sum(ALERT_WEIGHTS.values()) * 1.5
    weighted = sum(ALERT_WEIGHTS.get(a.code, 0.0) * (1.5 if a.severity == "alta" else 1.0)
                   for a in alerts)
    presion = round(min(100.0, weighted / max_possible * 100.0), 1) if max_possible else 0.0
    # INVERTIDA: 100 = ningún precursor activo, 0 = todos encendidos. En este documento cada
    # otro 0-100 es "más es mejor" —score global, sub-componentes, indicadores, percentiles—
    # y este era el único al revés: el original decía "0.0/100 (banda baja)", donde el número
    # gritaba lo peor y el paréntesis decía lo contrario. La polaridad va en el NOMBRE del
    # campo para que no se pueda leer al revés.
    score = round(100.0 - presion, 1)
    band = "baja" if score <= 45 else "media" if score <= 75 else "alta"
    # Ordena los Alert (tipados) por su peso calibrado antes de proyectarlos al dict de salida
    # — evita ordenar sobre el dict heterogéneo (weight quedaría como ``object``).
    ranked = sorted((a for a in alerts if a.code in ALERT_WEIGHTS),
                    key=lambda a: (-ALERT_WEIGHTS[a.code], a.code))
    contributors = [{"code": a.code, "label": a.label, "weight": ALERT_WEIGHTS[a.code],
                     "severity": a.severity} for a in ranked]
    return {"salud_precursores": score, "score": score, "band": band,
            "contributors": contributors, "n_calibradas": len(ALERT_WEIGHTS),
            # Las banderas activas que el índice NO cubre. Van con el score para que ninguna
            # superficie pueda mostrar el número sin mostrar lo que quedó afuera.
            "uncalibrated": [{"code": a.code, "label": a.label, "severity": a.severity}
                             for a in alerts if a.code not in ALERT_WEIGHTS]}


def classify_profile(m: Dict, alerts: List[Alert]) -> Optional[str]:
    """Dos naturalezas de riesgo que el histórico separa nítidamente:
      • 'agudo'   — deterioro reciente desde un estado sano → alerta temprana con lead real.
      • 'cronico' — morosidad alta SOSTENIDA (zombi tolerado): ya estaba podrida ~2 años atrás;
                    no hay 'temprano' que dar, la respuesta es NOMBRAR la insolvencia, no predecirla.
    Devuelve None si no hay señal de nivel de morosidad activa (nada que clasificar)."""
    floor = MOROSIDAD_FLOOR_BY_TYPE.get(m.get("bank_type") or "", DEFAULT_MOROSIDAD_FLOOR)
    mora_now = m.get("morosidad_pct")
    if mora_now is None or mora_now <= floor:
        return None
    mora_prior = m.get("morosidad_chronic")   # morosidad ~2 años atrás
    fired = {a.code for a in alerts}
    change_active = bool({"salto_morosidad", "erosion_capital"} & fired)
    was_sick = mora_prior is not None and mora_prior > floor
    if was_sick and not change_active:
        return "cronico"
    return "agudo"


def evaluate(m: Dict, peers: Dict) -> List[Alert]:
    """Todas las reglas sobre las métricas *m* de un banco + contexto de pares *peers*."""
    candidates = [
        rule_growth(m.get("assets_yoy"), peers.get("growth_p90")),
        rule_funding(m.get("funding_cost"), peers.get("funding_p90")),
        rule_coverage(m.get("cobertura_pct")),
        rule_morosidad(m.get("morosidad_pct"), m.get("morosidad_prev4")),
        rule_morosidad_nivel(m.get("morosidad_pct"), m.get("bank_type")),
        rule_capital_erosion(m.get("capital_now"), m.get("capital_prior")),
        rule_solvency(m.get("solvencia_pct")),
        rule_liquidity(m.get("liq_ratio"), m.get("deposit_qoq")),
        rule_concentration(m.get("concentracion_top10_deudores_pct"), m.get("is_state_owned", False)),
    ]
    order = {"alta": 0, "media": 1}
    return sorted((a for a in candidates if a is not None), key=lambda a: order.get(a.severity, 9))


# ── Orquestador (lee BankingData) ──────────────────────────────────────────────

def _bank_metrics(rows_by_period: Dict[date, "object"], period: date) -> Dict:
    """Métricas del banco en *period* (con histórico para YoY / 4T / QoQ)."""
    periods = sorted(rows_by_period)
    idx = periods.index(period)
    cur = rows_by_period[period]
    prev_q = rows_by_period[periods[idx - 1]] if idx >= 1 else None
    prev_4 = rows_by_period[periods[idx - 4]] if idx >= 4 else None
    prev_chr = rows_by_period[periods[idx - CHRONIC_LOOKBACK_Q]] if idx >= CHRONIC_LOOKBACK_Q else None

    def f(row, attr):
        v = getattr(row, attr, None) if row is not None else None
        return float(v) if v is not None else None

    return {
        "assets_yoy": _yoy(f(cur, "activos_totales"), f(prev_4, "activos_totales")),
        "funding_cost": _pct(f(cur, "gastos_financieros"), f(cur, "depositos_totales")),
        "cobertura_pct": f(cur, "cobertura_pct"),
        # Rezagos de 4T de los indicadores de NIVEL: sin ellos no hay velocidad, y sin
        # velocidad "ninguna alerta activa" no distingue estar lejos de estar yendo.
        "cobertura_prev4": f(prev_4, "cobertura_pct"),
        "solvencia_prev4": f(prev_4, "solvencia_pct"),
        "morosidad_pct": f(cur, "morosidad_pct"),
        "morosidad_prev4": f(prev_4, "morosidad_pct"),
        "morosidad_chronic": f(prev_chr, "morosidad_pct"),   # ~2 años atrás → distingue zombi de deterioro
        "solvencia_pct": f(cur, "solvencia_pct"),
        # Erosión de capital: proxy operativo = solvencia (Basel) hoy vs 4T atrás. Es el CAMBIO,
        # no el nivel (evita el falso positivo de la bandera de nivel revertida en #598).
        "capital_now": f(cur, "solvencia_pct"),
        "capital_prior": f(prev_4, "solvencia_pct"),
        "liq_ratio": _pct(f(cur, "activos_liquidos"), f(cur, "pasivos_exigibles")),
        "liq_ratio_prev4": _pct(f(prev_4, "activos_liquidos"),
                                f(prev_4, "pasivos_exigibles")),
        "deposit_qoq": _yoy(f(cur, "depositos_totales"), f(prev_q, "depositos_totales")),
        # DEFINICIÓN ÚNICA compartida con el motor de rating. Antes se recalculaba acá con
        # `cartera_bruta` mientras el indicador usaba `cartera_total`: el MISMO informe
        # mostraba 50,90% en Calidad de Activos y 51,5% en Alerta Temprana para el mismo
        # corte. No eran dos criterios: era el mismo cálculo escrito dos veces.
        "concentracion_top10_deudores_pct": (concentracion_top10_pct(cur) if cur is not None else None),
    }


def compute_alerts(db: Session, period: Optional[date] = None) -> Dict:
    """Evalúa las 7 alertas por banco en el último período (o *period*). Devuelve el bloque
    del sistema: bancos con banderas activas ordenados por severidad, + resumen por código."""
    from modules.banking_score.models.models import Bank, BankingData

    monitored = db.query(Bank).filter(
        Bank.is_active.is_(True), Bank.bank_type.in_(MONITORED_TYPES)).all()
    names = {b.id: b.name for b in monitored}
    types = {str(b.id): b.bank_type for b in monitored}
    by_bank: Dict[str, Dict[date, object]] = {}
    for r in db.query(BankingData).all():
        if r.bank_id in names:
            by_bank.setdefault(r.bank_id, {})[r.period_end] = r
    if not by_bank:
        return {"period": None, "banks": [], "summary": {}, "n_alerts": 0}

    target = period or max(p for rows in by_bank.values() for p in rows)
    metrics = {bid: _bank_metrics(rows, target) for bid, rows in by_bank.items() if target in rows}
    peers = {
        "growth_p90": percentile([m["assets_yoy"] for m in metrics.values()
                                  if m["assets_yoy"] is not None], 0.90),
        "funding_p90": percentile([m["funding_cost"] for m in metrics.values()
                                   if m["funding_cost"] is not None], 0.90),
    }

    from modules.banking_score.scoring.support import STATE_OWNED
    # Ids de entidades de propiedad estatal (una pasada; evita acceso indexado al dict
    # ``names`` —tipado con claves Column por el modelo— dentro del loop).
    state_ids = {b for b, nm in names.items() if nm in STATE_OWNED}

    banks: List[Dict] = []
    summary: Dict[str, int] = {}
    profiles: Dict[str, int] = {}
    panels: Dict[str, List[Dict]] = {}
    for bid, m in metrics.items():
        # Naturaleza de la entidad → la bandera de concentración se encuadra distinto en
        # banca estatal (concentración estructural por mandato, no proxy de vinculados); y el
        # umbral de morosidad de nivel es relativo al tipo.
        m["is_state_owned"] = bid in state_ids
        m["bank_type"] = types.get(str(bid), None)
        # El panel se computa para TODA entidad monitoreada, tenga o no banderas: su valor
        # está justo cuando no hay ninguna activa (a qué distancia quedó de cada umbral), y
        # esas entidades salen del loop en la línea siguiente.
        panels[bid] = signal_panel(m, peers)
        alerts = evaluate(m, peers)
        if not alerts:
            continue
        ens = ensemble_score(alerts)
        perfil = classify_profile(m, alerts)
        for a in alerts:
            summary[a.code] = summary.get(a.code, 0) + 1
        if perfil:
            profiles[perfil] = profiles.get(perfil, 0) + 1
        banks.append({
            "bank_id": bid, "name": names.get(bid, bid),
            "max_severity": alerts[0].severity,
            "score": ens["score"], "band": ens["band"], "perfil": perfil,
            "ensemble": ens, "panel": panels.get(bid, []),
            "alerts": [asdict(a) for a in alerts],
        })
    # Orden por presión del conjunto (score), luego severidad — el conjunto ponderado manda.
    # Las entidades NO puntuables van en un tramo aparte, ordenadas por severidad, y no
    # mapeadas a 0: tratarlas como score 0 las hundiría por debajo de cualquier entidad con
    # presión mínima, que es el mismo defecto del cero fabricado mudado al ranking (una
    # concentración del 50.9% quedaría debajo de un score 5).
    banks.sort(key=lambda b: (-float(b["score"]), b["max_severity"] != "alta", b["name"]))
    # Entidades cuyas banderas activas quedan TODAS fuera del índice: su score es un 0
    # legítimo sobre el dominio calibrado, así que ordenan al final — pero el panel necesita
    # saber que existen, o una concentración del 50,9% desaparece al fondo de la lista sin
    # que nadie note que hay una señal encendida.
    solo_fuera = sum(1 for b in banks if not (b["ensemble"].get("contributors") or []))
    return {"period": target.isoformat(), "banks": banks, "summary": summary,
            "panels": panels,
            "profiles": profiles, "n_alerts": sum(len(b["alerts"]) for b in banks),
            "n_solo_señales_fuera_del_indice": solo_fuera}


def bank_alerts(db: Session, bank_id: str, period: Optional[date] = None) -> Dict:
    """Alertas de UNA entidad EN *period* (el corte del informe), o al último si no se indica.

    El parámetro existe porque sin él el bloque de alertas de un Deep Dive "al 31-dic-2025"
    mostraba el corte de marzo-2026: el MISMO informe reportaba la concentración top-10 en
    50,9% (§Calidad de Activos, dic) y 51,5% (§Alerta Temprana, mar). Se leía como dato
    inconsistente cuando en realidad eran dos FECHAS. Misma familia que la trayectoria y las
    capas de contexto: el corte del informe manda sobre todo lo que muestra.
    """
    block = compute_alerts(db, period)
    entry = next((b for b in block["banks"] if b["bank_id"] == bank_id), None)
    return {"period": block["period"],
            "alerts": entry["alerts"] if entry else [],
            "max_severity": entry["max_severity"] if entry else None,
            "score": entry["score"] if entry else None,
            "band": entry["band"] if entry else None,
            "perfil": entry["perfil"] if entry else None,
            # El panel viaja SIEMPRE, aunque la entidad no tenga banderas: sin él, un
            # "sin alertas" no dice si el banco está holgado o a un pelo del umbral.
            "panel": (entry or {}).get("panel") or block.get("panels", {}).get(bank_id, []),
            "ensemble": (entry or {}).get("ensemble")}


def _prosa_margenes(panel: List[Dict]) -> str:
    """Los márgenes en PROSA. El Deep Dive narra; siete viñetas son el registro del Insight.

    La salvedad va en la GRAMÁTICA, no en un rótulo: «de sostenerse el ritmo» es condicional
    y cualquiera en una sala de comité lo entiende, mientras que un «lectura mecánica, no
    proyección» entre paréntesis le avisa al lector que desconfíe de la frase que acaba de
    leer. El hecho medido se afirma sin adornos; lo que depende de que algo continúe se
    escribe como lo que es: una condición.
    """
    if not panel:
        return ""
    r = panel_relations(panel)
    partes: List[str] = []
    if r["activos"]:
        act = ", ".join(f"{a['label'].lower()} ({a['metric']} en {a['value']}, umbral "
                        f"{a['threshold']})" for a in r["activos"])
        partes.append(f"De los {r['n_evaluables']} precursores evaluables, {r['n_activos']} "
                      f"están activos: {act}.")
    else:
        partes.append(f"Ninguno de los {r['n_evaluables']} precursores evaluables está activo "
                      f"al corte.")
    cp = r["converge_primero"]
    if cp:
        plazo = (f" De sostenerse el ritmo de los últimos cuatro trimestres, alcanzaría el "
                 f"umbral de {cp['threshold']} en unos {cp['trimestres_al_umbral']:.0f} "
                 f"trimestres." if cp["trimestres_al_umbral"] else "")
        desde = round(cp["value"] - (cp["velocidad_4t"] or 0), 2)
        cabeza = ("El que se acerca es" if r["n_convergen"] == 1 else "El que llega antes es")
        partes.append(f"{cabeza} {cp['label'].lower()}: pasó de {desde} a {cp['value']} en "
                      f"doce meses.{plazo}")
        if r["n_convergen"] == 1:
            partes.append("Es el único que se mueve hacia su umbral; los demás se mantienen "
                          "estables o se alejan.")
        else:
            # Se NOMBRAN con su horizonte: "otros N convergen" esconde justo lo que el comité
            # necesita vigilar. El orden ya viene computado, en trimestres — la única unidad
            # comparable entre precursores de escalas distintas.
            resto = "; ".join(f"{c['label'].lower()}, en unos {c['trimestres_al_umbral']:.0f}"
                              for c in r["convergen"][1:])
            partes.append(f"También se mueven hacia su umbral {resto} trimestres.")
    elif not r["activos"]:
        partes.append("Ninguno converge hacia su umbral: en los últimos doce meses todos se "
                      "mantuvieron estables o se alejaron.")
    if r["sin_dato"]:
        # Una regla sin su input no falla, DESAPARECE. Se nombra o el lector la cuenta como sana.
        partes.append(f"Sin dato para evaluar al corte: "
                      f"{', '.join(x.lower() for x in r['sin_dato'])}.")
    return " ".join(partes)


def format_alerts_text(block: Optional[Dict]) -> str:
    """Bloque de alertas → texto markdown para la sección del reporte (determinista, sin IA)."""
    alerts = (block or {}).get("alerts") or []
    panel = (block or {}).get("panel") or []
    if not alerts:
        cab = ("Sin banderas de alerta temprana activas al período de corte. Las señales de "
               "monitoreo —precursores detectables de la crisis bancaria de 2003— no se activaron "
               "para esta entidad. Es un complemento del rating, no un veredicto, y no detecta "
               "fraude ni contabilidad paralela.")
        # Con el panel, "sin banderas" deja de ser un no-dato: se ve el colchón de cada señal.
        prosa = _prosa_margenes(panel)
        return "\n\n".join([cab] + ([prosa] if prosa else []))
    lines = ["Señales de monitoreo activas —precursores detectables de la crisis bancaria de 2003 "
        "(complemento del rating, no un veredicto; no detectan fraude):", ""]
    ens = (block or {}).get("ensemble")
    score = (block or {}).get("score")
    band = (block or {}).get("band")
    if score is None and ens:
        score, band = ens.get("score"), ens.get("band")
    perfil = (block or {}).get("perfil")
    if score is not None:
        etiqueta = {"agudo": "deterioro agudo (alerta temprana con anticipación real)",
                    "cronico": "insolvencia crónica (zombi tolerado; no es un deterioro nuevo)"}.get(perfil or "")
        # El encabezado declara el DOMINIO del índice. Cuando ninguna calibrada está activa,
        # el 0/100 se afirma como lo que es —un resultado— en vez de dejarlo leer como
        # all-clear del conjunto entero.
        n_cal = (ens or {}).get("n_calibradas") or len(ALERT_WEIGHTS)
        contribuyen = (ens or {}).get("contributors") or []
        rel = panel_relations(panel) if panel else {}
        cobertura = (ENSEMBLE_COBERTURA.format(evaluables=rel["n_evaluables"],
                                               calibradas=rel["n_calibradas"])
                     if rel else "")
        cab = f"{ENSEMBLE_ENCABEZADO}: **{score}/100**"
        if cobertura:
            cab += f" · {cobertura}"
        cab += (f" — {ENSEMBLE_NINGUNO_ACTIVO}" if not contribuyen else f" (banda {band})")
        if etiqueta:
            cab += f" — perfil: {etiqueta}"
        prosa = _prosa_margenes(panel)
        lines = [cab + ".", ""] + ([prosa, ""] if prosa else []) + lines
    for a in alerts:
        # Una bandera sin peso se marca en su propia línea: es la que el índice no cubre, y
        # sin la marca el lector la cuenta como parte del número de arriba.
        fuera = "" if a.get("code", "") in ALERT_WEIGHTS else f" · {ENSEMBLE_FUERA_DEL_INDICE}"
        lines.append(f"- **{a['label']}** ({a['severity']}{fuera}) — {a['metric']}: "
                     f"{a['value']} (umbral {a['threshold']}). {a['basis']}.")
    return "\n".join(lines)
