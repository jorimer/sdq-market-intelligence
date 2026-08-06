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
CONCENTRATION = 30.0       # top-10 / cartera bruta %  (proxy de vinculados)

# ── Calibración del CONJUNTO ponderado (derivada del histórico SIB) ─────────────
# La alerta temprana no es una señal suelta: es un CONJUNTO con pesos. Estos se calibraron
# sobre la cohorte de 35 terminaciones AGUDAS del histórico SIB (entidades que venían sanas,
# se deterioraron y salieron del sistema — la etiqueta económica correcta en un régimen que
# absorbía/renombraba en vez de quebrar formalmente), con regresión logística estandarizada
# validada leave-one-entity-out. Reproducen el peso con que cada señal separó quiebras de
# sobrevivientes; no son ad-hoc. Hallazgos que codifican:
#   • la morosidad (nivel 0.38 + salto 0.11) domina, pero NO es sola;
#   • cobertura (0.20) y erosión de capital (0.14) suman ~1/3 del conjunto;
#   • el boom de crédito (0.08) es la señal MÁS temprana (la burbuja precede al estallido);
#   • la fuga de depósitos (0.02) pesa poco: CONFIRMA tarde (dispara en 14/35 casos), no anticipa.
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
    return Alert("concentracion", "Concentración elevada (top-10)", "media",
                 round(concentration_pct, 1), CONCENTRATION, basis,
                 "top-10 / cartera bruta %")


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


def ensemble_score(alerts: List[Alert]) -> Dict:
    """Puntaje del CONJUNTO ponderado (0..100): la alerta temprana como suma de señales con
    sus pesos calibrados, no como banderas sueltas. Una 'alta' cuenta 1.5× su peso base.
    Devuelve el score, su banda y las señales que contribuyen ordenadas por peso."""
    max_possible = sum(ALERT_WEIGHTS.values()) * 1.5
    weighted = sum(ALERT_WEIGHTS.get(a.code, 0.0) * (1.5 if a.severity == "alta" else 1.0)
                   for a in alerts)
    score = round(min(100.0, weighted / max_possible * 100.0), 1) if max_possible else 0.0
    band = "alta" if score >= 55 else "media" if score >= 25 else "baja"
    # Ordena los Alert (tipados) por su peso calibrado antes de proyectarlos al dict de salida
    # — evita ordenar sobre el dict heterogéneo (weight quedaría como ``object``).
    ranked = sorted((a for a in alerts if a.code in ALERT_WEIGHTS),
                    key=lambda a: (-ALERT_WEIGHTS[a.code], a.code))
    contributors = [{"code": a.code, "label": a.label, "weight": ALERT_WEIGHTS[a.code],
                     "severity": a.severity} for a in ranked]
    return {"score": score, "band": band, "contributors": contributors}


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
        rule_concentration(m.get("concentration_pct"), m.get("is_state_owned", False)),
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
        "morosidad_pct": f(cur, "morosidad_pct"),
        "morosidad_prev4": f(prev_4, "morosidad_pct"),
        "morosidad_chronic": f(prev_chr, "morosidad_pct"),   # ~2 años atrás → distingue zombi de deterioro
        "solvencia_pct": f(cur, "solvencia_pct"),
        # Erosión de capital: proxy operativo = solvencia (Basel) hoy vs 4T atrás. Es el CAMBIO,
        # no el nivel (evita el falso positivo de la bandera de nivel revertida en #598).
        "capital_now": f(cur, "solvencia_pct"),
        "capital_prior": f(prev_4, "solvencia_pct"),
        "liq_ratio": _pct(f(cur, "activos_liquidos"), f(cur, "pasivos_exigibles")),
        "deposit_qoq": _yoy(f(cur, "depositos_totales"), f(prev_q, "depositos_totales")),
        # DEFINICIÓN ÚNICA compartida con el motor de rating. Antes se recalculaba acá con
        # `cartera_bruta` mientras el indicador usaba `cartera_total`: el MISMO informe
        # mostraba 50,90% en Calidad de Activos y 51,5% en Alerta Temprana para el mismo
        # corte. No eran dos criterios: era el mismo cálculo escrito dos veces.
        "concentration_pct": (concentracion_top10_pct(cur) if cur is not None else None),
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
    for bid, m in metrics.items():
        # Naturaleza de la entidad → la bandera de concentración se encuadra distinto en
        # banca estatal (concentración estructural por mandato, no proxy de vinculados); y el
        # umbral de morosidad de nivel es relativo al tipo.
        m["is_state_owned"] = bid in state_ids
        m["bank_type"] = types.get(str(bid), None)
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
            "ensemble": ens,
            "alerts": [asdict(a) for a in alerts],
        })
    # Orden por presión del conjunto (score), luego severidad — el conjunto ponderado manda.
    banks.sort(key=lambda b: (-float(b["score"]), b["max_severity"] != "alta", b["name"]))
    return {"period": target.isoformat(), "banks": banks, "summary": summary,
            "profiles": profiles, "n_alerts": sum(len(b["alerts"]) for b in banks)}


def bank_alerts(db: Session, bank_id: str) -> Dict:
    """Alertas de UNA entidad al último período (para el deep dive / endpoint por-banco)."""
    block = compute_alerts(db)
    entry = next((b for b in block["banks"] if b["bank_id"] == bank_id), None)
    return {"period": block["period"],
            "alerts": entry["alerts"] if entry else [],
            "max_severity": entry["max_severity"] if entry else None,
            "score": entry["score"] if entry else None,
            "band": entry["band"] if entry else None,
            "perfil": entry["perfil"] if entry else None}


def format_alerts_text(block: Optional[Dict]) -> str:
    """Bloque de alertas → texto markdown para la sección del reporte (determinista, sin IA)."""
    alerts = (block or {}).get("alerts") or []
    if not alerts:
        return ("Sin banderas de alerta temprana activas al período de corte. Las señales de "
                "monitoreo —precursores detectables de la crisis bancaria de 2003— no se activaron "
                "para esta entidad. Es un complemento del rating, no un veredicto, y no detecta "
                "fraude ni contabilidad paralela.")
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
        cab = f"Índice de presión de deterioro del conjunto: **{score}/100** (banda {band})"
        if etiqueta:
            cab += f" — perfil: {etiqueta}"
        lines = [cab + ".", ""] + lines
    for a in alerts:
        lines.append(f"- **{a['label']}** ({a['severity']}) — {a['metric']}: {a['value']} "
                     f"(umbral {a['threshold']}). {a['basis']}.")
    return "\n".join(lines)
