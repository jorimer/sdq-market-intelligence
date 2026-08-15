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
# Pesos DERIVADOS DE LA EVIDENCIA, promediando sobre diez especificaciones — `ew_calibration`
# con sus seis recetas de cohorte, la cohorte canónica de `terminaciones` a 6/12/24 meses, y
# el modelo de riesgo de `hazard`. Se promedia en vez de elegir una porque la receta es un
# parámetro libre: fijar la que más guste sería elegir el resultado. Integrar sobre ella es
# más defendible, y el RANGO observado va anotado al lado de cada peso para que nadie lea
# estos números como más precisos de lo que son.
#
# Lo que reemplazaron: una calibración que se documentaba como "35 terminaciones agudas, AUC
# 0.88" y que no existía como código. Ver el encabezado de `validation/ew_calibration.py`.
#
# Los dos cambios grandes, y por qué se sostienen:
#   • estres_liquidez pasa de 0.02 a 0.36. Sale material en las DIEZ especificaciones y es la
#     más pesada en el modelo de riesgo. La glosa anterior decía "pesa poco: CONFIRMA tarde,
#     dispara en 14/35 casos, no anticipa" — el histórico dice lo contrario.
#   • crecimiento_anomalo queda en CERO. Da cero en las diez, sin una sola excepción. Se
#     documentaba como "la señal MÁS temprana (la burbuja precede al estallido)". Se deja en
#     el dict con peso 0 en vez de borrarlo: "se midió y no predice" es una afirmación más
#     fuerte y más útil que "no se pudo medir", y son cosas distintas.
#
# solvencia_piso conserva su 0.06 y NO viene de esta evidencia: Basilea es regulatoria y no
# existe pre-2004, así que no entra en ninguna matriz (ver `sib_basel_reconstruction`, donde
# la reconstrucción quedó con ±4.6 pp de error, demasiado ancho para una regla de umbral). Se
# mantiene por su base normativa, declarado como no verificable con esta fuente.
#
# ANTES DE TOCARLOS: corré `ew_calibration.sensitivity_table()` y `hazard.ajustar()`. Y tené
# presente que el ajuste sobre etiquetas CURADAS todavía no gradúa —8 eventos, mínimo 10—, así
# que estos pesos salen de etiquetas mayormente inferidas: son la mejor evidencia disponible,
# no una validación cerrada.
ALERT_WEIGHTS: Dict[str, float] = {
    "estres_liquidez": 0.364,      # rango entre recetas 0.00–0.75 · antes 0.02
    "morosidad_nivel": 0.312,      # 0.00–1.00 · antes 0.38
    "salto_morosidad": 0.117,      # 0.00–0.40 · antes 0.11
    "brecha_provisiones": 0.096,   # 0.00–0.54 · antes 0.20
    "solvencia_piso": 0.060,       # NO verificable con esta fuente; se conserva por norma
    "erosion_capital": 0.051,      # 0.00–0.15 · antes 0.14
    "crecimiento_anomalo": 0.000,  # 0.00–0.00 en las diez · antes 0.08
    # concentracion / fondeo_caro: sin peso. La concentración además se MIDIÓ contra deterioro
    # de cartera en la ventana donde el top-10 existe (2021-2026) y no anticipa: AUC 0.48,
    # IC que cruza cero en cuatro umbrales. Ver `validation/concentracion_calibration.py`.
}

# La prosa que se PUBLICA vive en constantes, no incrustada en un f-string: un literal
# partido por ancho de línea deja de existir en el fuente aunque el valor salga bien, y un
# test que lo busque ahí falla sin motivo (o pasa sin protegerte).
# El rótulo dice QUÉ mide el índice. Decir "del conjunto" prometía cubrir las nueve reglas
# cuando solo pondera siete, y con eso un 0.0 legítimo se leía como all-clear global.
ENSEMBLE_ENCABEZADO = "Índice de salud frente a las señales de deterioro temprano"
ENSEMBLE_COBERTURA = "{evaluables} de {calibradas} señales con dato al corte"
ENSEMBLE_NINGUNO_ACTIVO = "ninguna encendida"
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


# ── Cómo se NOMBRA y se EXPRESA cada precursor en el informe ───────────────────
# Los `code`/`label` de las reglas son nombres internos —"brecha de provisiones",
# "morosidad sobre el umbral de su tipo", "solvencia cerca del piso"— y se estaban filtrando
# al PDF como si fueran categorías que el lector conoce. Acá viven el concepto en lenguaje de
# riesgo, la unidad en que la cifra se entiende, y QUÉ SIGNIFICA cruzar el umbral. Sin eso el
# informe publicaba "pasó de 229.67 a 200.6" y "alcanzaría el umbral de 100.0", que no dicen
# de qué son esos números ni qué pasa al cruzarlos.
#   forma: "pct"      → 15.37  ⇒ "15,4%"
#          "veces"    → 200.6  ⇒ "2,0 veces"   (un ratio publicado en base 100)
#          "pp_var"   → -1.0   ⇒ "1,0 punto"   (una variación en puntos)
SIGNAL_META: Dict[str, Dict[str, str]] = {
    "morosidad_nivel": {
        "concepto": "la morosidad de la cartera",
        "forma": "pct",
        "umbral_significa": "la mora supera lo habitual para una entidad de su tipo",
    },
    "brecha_provisiones": {
        "concepto": "la cobertura de provisiones",
        "forma": "veces",
        "umbral_significa": "las reservas dejan de cubrir la cartera vencida",
    },
    "erosion_capital": {
        "concepto": "la erosión del capital",
        "forma": "pp_var",
        "umbral_significa": "el capital sobre activos cede más de un punto en doce meses",
    },
    "salto_morosidad": {
        "concepto": "el salto de la morosidad",
        "forma": "pct",
        "umbral_significa": "la mora crece la mitad o más respecto de un año atrás",
    },
    "crecimiento_anomalo": {
        "concepto": "la expansión del balance",
        "forma": "pct",
        "umbral_significa": "los activos crecen más rápido que el 90% del sistema",
    },
    "solvencia_piso": {
        "concepto": "la solvencia",
        "forma": "pct",
        "umbral_significa": "el capital regulatorio se aproxima al mínimo legal de 10%",
    },
    "estres_liquidez": {
        "concepto": "la salida de depósitos",
        "forma": "pct",
        "umbral_significa": "los depósitos caen 10% o más en un trimestre",
    },
    # Las dos que quedan fuera del índice ponderado se publican igual, y con el mismo
    # cuidado: son las que el lector ve en la lista de señales activas.
    # sujeto-ok: la clave es el CODE de la regla, no una cifra; su población la nombra
    # `concepto` ("los diez mayores deudores") y viaja con el número al informe.
    "concentracion": {
        "concepto": "la concentración en los diez mayores deudores",
        "forma": "pct",
        "umbral_significa": "los diez mayores deudores superan el 30% de la cartera",
    },
    "fondeo_caro": {
        "concepto": "el costo de fondeo",
        "forma": "pct",
        "umbral_significa": "la entidad paga por sus depósitos más que el 90% del sistema",
    },
}

# Más allá de este horizonte una convergencia no se distingue del ruido, y tampoco es
# accionable: reportar que un indicador "se mueve hacia su umbral" a doce o quince años es
# disfrazar ruido de señal. Cinco años es el borde: cubre el horizonte de una decisión de
# crédito (la cobertura de BPD, a 3,5 años, SÍ importa) y descarta los plazos de una década.
HORIZONTE_MATERIAL_Q = 20


def _expresar(valor: Optional[float], forma: str) -> str:
    """La cifra como la leería un comité, con su unidad. Nunca el número pelado."""
    if valor is None:
        return "sin dato"
    # Separador decimal: PUNTO. Es la convención de RD ("RD$1,234.56") y la del resto del
    # informe — medido sobre un Deep Dive generado en producción, 133 cifras con punto contra
    # 8 con coma. Una primera versión de esta función usó coma y quedó como la única sección
    # fuera de convención: dentro del MISMO párrafo convivían "2,3 veces" y el "2.3 veces" del
    # modelo, que se lee como un error de datos.
    if forma == "veces":
        v = valor / 100
        if abs(v - 1.0) < 0.05:
            return "1 vez"           # "1.0 veces" es la frontera; se dice en singular
        return f"{v:.1f} veces"
    if forma == "pp_var":
        n = f"{abs(valor):.1f}".rstrip("0").rstrip(".")
        return f"{n} punto{'s' if abs(valor) != 1 else ''}"
    # Dos decimales solo si aportan: "50.90%" finge una precisión que el dato no tiene.
    txt = f"{valor:,.2f}"
    if txt.endswith("0"):
        txt = txt[:-1].rstrip(".")
    return txt + "%"


def _horizonte(trimestres: Optional[float]) -> Optional[str]:
    """Trimestres → la unidad en que un comité razona. Bajo un año y medio, trimestres;
    más allá, años — «59 trimestres» obliga al lector a dividir."""
    if trimestres is None:
        return None
    if trimestres < 6:
        return f"unos {trimestres:.0f} trimestres"
    anios = trimestres / 4.0
    return f"alrededor de {anios:.1f} años"


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
            out.append({"code": code, "label": label, "metric": metric,
                        "concepto": SIGNAL_META.get(code, {}).get("concepto", label.lower()),
                        "value": None, "threshold": umbral, "estado": "sin_dato",
                        "margen": None, "velocidad_4t": None, "direccion": None,
                        "trimestres_al_umbral": None, "horizonte": None,
                        "convergencia_material": False})
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
        meta = SIGNAL_META.get(code, {})
        forma = meta.get("forma", "pct")
        # Materialidad: una convergencia a doce o quince años no es una convergencia. Se
        # conserva la dirección (el hecho) y se descarta el plazo (el ruido).
        material = trimestres is not None and trimestres <= HORIZONTE_MATERIAL_Q
        out.append({"code": code, "label": label, "metric": metric,
                    "concepto": meta.get("concepto", label.lower()),
                    "value": round(valor, 2), "threshold": round(umbral, 2),
                    "valor_expresado": _expresar(valor, forma),
                    "umbral_expresado": _expresar(umbral, forma),
                    "umbral_significa": meta.get("umbral_significa", ""),
                    "hace_12m_expresado": (_expresar(valor - vel, forma)
                                           if vel is not None else None),
                    "estado": "activa" if activa else "sin_activar",
                    "margen": round(margen, 2),
                    "velocidad_4t": None if vel is None else round(vel, 2),
                    "direccion": direccion, "trimestres_al_umbral": trimestres,
                    "horizonte": _horizonte(trimestres) if material else None,
                    "convergencia_material": material})
    return out


def panel_para_modelo(panel: List[Dict]) -> List[Dict]:
    """El panel SIN los números crudos: solo las cadenas ya redactadas.

    Instruirle al modelo "no uses `value`, usá `valor_expresado`" es frágil —al verificar en
    producción escribió "2.3 veces" y "50.9%" junto a "2,3" del bloque determinista, dos
    notaciones decimales en el mismo párrafo—. La cura no es una regla más en el prompt: es
    no darle el número crudo. Si la forma también se computa, tampoco puede reformatearla.
    """
    return [{"concepto": s.get("concepto"), "estado": s["estado"],
             "direccion": s.get("direccion"),
             "valor": s.get("valor_expresado"), "umbral": s.get("umbral_expresado"),
             "hace_12m": s.get("hace_12m_expresado"),
             "umbral_significa": s.get("umbral_significa"),
             "horizonte_al_umbral": s.get("horizonte")}
            for s in panel]


def relaciones_para_modelo(panel: List[Dict]) -> Dict:
    """Las relaciones sin los números crudos — misma razón que `panel_para_modelo`: si el
    valor pelado no está, no se puede reformatear ni recalcular."""
    r = panel_relations(panel)
    def _slim(x):
        if not x:
            return None
        return {"concepto": x.get("concepto"), "valor": x.get("valor_expresado"),
                "umbral": x.get("umbral_expresado"), "hace_12m": x.get("hace_12m_expresado"),
                "umbral_significa": x.get("umbral_significa"),
                "horizonte_al_umbral": x.get("horizonte")}
    return {"n_calibradas": r["n_calibradas"], "n_evaluables": r["n_evaluables"],
            "n_activos": r["n_activos"], "n_convergen": r["n_convergen"],
            "n_se_alejan": r["n_se_alejan"], "sin_dato": r["sin_dato"],
            "converge_primero": _slim(r["converge_primero"]),
            "convergen": [_slim(x) for x in r["convergen"]],
            "activos": [_slim(x) for x in r["activos"]]}


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
                        and s.get("convergencia_material")),
                       key=lambda s: s["trimestres_al_umbral"])
    se_alejan = [s for s in medibles
                 if s["estado"] == "sin_activar" and s.get("direccion") in ("se_aleja", "estable")]

    def _ref(s):
        # sujeto-ok: cada cifra viaja con el precursor que la produce en `label`; no es una
        # cuota sobre una población.
        return {"label": s["label"], "concepto": s.get("concepto"), "metric": s["metric"],
                "value": s["value"], "threshold": s["threshold"], "margen": s["margen"],
                "valor_expresado": s.get("valor_expresado"),
                "umbral_expresado": s.get("umbral_expresado"),
                "umbral_significa": s.get("umbral_significa"),
                "hace_12m_expresado": s.get("hace_12m_expresado"),
                "velocidad_4t": s.get("velocidad_4t"), "horizonte": s.get("horizonte"),
                "trimestres_al_umbral": s.get("trimestres_al_umbral")}

    return {
        "n_calibradas": len(panel),
        "n_evaluables": len(medibles),
        "n_activos": len(activos),
        "n_convergen": len(convergen),
        "n_se_alejan": len(se_alejan),
        "sin_dato": [s["label"] for s in panel if s["estado"] == "sin_dato"],
        "sin_dato_codes": [s["code"] for s in panel if s["estado"] == "sin_dato"],
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
    """Los márgenes en PROSA, para un comité — no todos son técnicos en riesgo.

    Tres cosas que la versión anterior no hacía y volvían el párrafo ilegible: la cifra sale
    con su UNIDAD ("2,0 veces", no "200,6"), el precursor se nombra por su CONCEPTO y no por
    el nombre interno de la regla ("la cobertura de provisiones", no "brecha de
    provisiones"), y el umbral se explica por lo que SIGNIFICA cruzarlo ("las reservas dejan
    de cubrir la cartera vencida", no "el umbral de 100,0").

    La salvedad va en la gramática —«de sostenerse el ritmo»— y no en un rótulo entre
    paréntesis, que le avisaría al lector que desconfíe de la frase que acaba de leer.
    """
    if not panel:
        return ""
    r = panel_relations(panel)
    partes: List[str] = []
    if r["activos"]:
        # Con muchas encendidas, el párrafo NOMBRA y las viñetas explican. Repetir "cuando la
        # señal se activa si…" siete veces vuelve el texto ilegible y duplica la lista.
        if r["n_activos"] > 3:
            act = "; ".join(f"{a['concepto']} en {a['valor_expresado']}" for a in r["activos"])
            partes.append(f"Las {r['n_activos']} señales de deterioro temprano evaluables "
                          f"están encendidas: {act}. El detalle de cada umbral va abajo.")
        else:
            act = "; ".join(f"{a['concepto']} en {a['valor_expresado']}, cuando la señal se "
                            f"activa si {a['umbral_significa']}" for a in r["activos"])
            partes.append(f"De las {r['n_evaluables']} señales de deterioro temprano "
                          f"evaluables, {r['n_activos']} están encendidas: {act}.")
    else:
        partes.append(f"Ninguna de las {r['n_evaluables']} señales de deterioro temprano está "
                      f"encendida.")
    cp = r["converge_primero"]
    if cp:
        movimiento = (f" pasó de {cp['hace_12m_expresado']} a {cp['valor_expresado']} en doce "
                      f"meses" if cp["hace_12m_expresado"] else
                      f" está en {cp['valor_expresado']}")
        plazo = (f" De sostenerse el ritmo del último año, eso tomaría {cp['horizonte']}."
                 if cp["horizonte"] else "")
        partes.append(f"La que más se movió es {cp['concepto']}:{movimiento}. La señal se "
                      f"activa cuando {cp['umbral_significa']}, es decir "
                      f"{cp['umbral_expresado']}.{plazo}")
        if r["n_convergen"] > 1:
            resto = "; ".join(f"{c['concepto']}, {c['horizonte']}" for c in r["convergen"][1:])
            partes.append(f"También se acercan {resto}.")
        else:
            partes.append("Ninguna otra se aproxima a su umbral en un horizonte relevante "
                          "para esta decisión.")
    elif not r["activos"]:
        partes.append("Ninguna se aproxima a su umbral en un horizonte relevante para esta "
                      "decisión.")
    if r["sin_dato"]:
        # Una regla sin su input no falla, DESAPARECE. Se nombra o el lector la cuenta como sana.
        faltan = ", ".join(SIGNAL_META.get(c, {}).get("concepto", c)
                           for c in r["sin_dato_codes"])
        partes.append(f"Sin dato para evaluar al corte: {faltan}.")
    return " ".join(partes)


def format_alerts_text(block: Optional[Dict]) -> str:
    """Bloque de alertas → markdown de la sección (determinista, sin IA).

    ``con_narrativa=True`` en el bloque omite la prosa de márgenes: cuando el modelo YA la
    narró arriba, imprimirla otra vez hace que la sección diga lo mismo dos veces —el defecto
    que apareció al verificar en producción—. El encabezado con el índice y las viñetas se
    quedan siempre: son los hechos estructurados, no una repetición del párrafo.
    """
    alerts = (block or {}).get("alerts") or []
    panel = (block or {}).get("panel") or []
    if (block or {}).get("con_narrativa"):
        panel = []
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
        code = a.get("code") or ""
        # Sin `code` no se puede saber si está dentro del índice; marcar "fuera" sería
        # afirmar de más. El default calla, no acusa.
        fuera = (f", {ENSEMBLE_FUERA_DEL_INDICE}"
                 if code and code not in ALERT_WEIGHTS else "")
        meta = SIGNAL_META.get(a.get("code", ""), {})
        forma = meta.get("forma", "pct")
        # Prosa, no notación de fórmula: "top-10 / cartera total %: 50.9 (umbral 30.0)" es
        # una expresión de motor, no una frase que alguien lea en un comité.
        concepto = meta.get("concepto", a["label"].lower())
        signif = meta.get("umbral_significa")
        cuando = f" La señal se activa cuando {signif}." if signif else ""
        lines.append(f"- **{a['label']}** (severidad {a['severity']}{fuera}) — {concepto} está "
                     f"en {_expresar(a['value'], forma)}, frente a "
                     f"{_expresar(a['threshold'], forma)} de referencia.{cuando} {a['basis']}.")
    return "\n".join(lines)
