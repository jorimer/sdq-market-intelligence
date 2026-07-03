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


def rule_concentration(concentration_pct: Optional[float]) -> Optional[Alert]:
    if concentration_pct is None or concentration_pct <= CONCENTRATION:
        return None
    return Alert("concentracion", "Concentración elevada (top-10)", "media",
                 round(concentration_pct, 1), CONCENTRATION,
                 "Los préstamos vinculados fueron el corazón del fraude (proxy visible)",
                 "top-10 / cartera bruta %")


def evaluate(m: Dict, peers: Dict) -> List[Alert]:
    """Todas las reglas sobre las métricas *m* de un banco + contexto de pares *peers*."""
    candidates = [
        rule_growth(m.get("assets_yoy"), peers.get("growth_p90")),
        rule_funding(m.get("funding_cost"), peers.get("funding_p90")),
        rule_coverage(m.get("cobertura_pct")),
        rule_morosidad(m.get("morosidad_pct"), m.get("morosidad_prev4")),
        rule_solvency(m.get("solvencia_pct")),
        rule_liquidity(m.get("liq_ratio"), m.get("deposit_qoq")),
        rule_concentration(m.get("concentration_pct")),
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

    def f(row, attr):
        v = getattr(row, attr, None) if row is not None else None
        return float(v) if v is not None else None

    return {
        "assets_yoy": _yoy(f(cur, "activos_totales"), f(prev_4, "activos_totales")),
        "funding_cost": _pct(f(cur, "gastos_financieros"), f(cur, "depositos_totales")),
        "cobertura_pct": f(cur, "cobertura_pct"),
        "morosidad_pct": f(cur, "morosidad_pct"),
        "morosidad_prev4": f(prev_4, "morosidad_pct"),
        "solvencia_pct": f(cur, "solvencia_pct"),
        "liq_ratio": _pct(f(cur, "activos_liquidos"), f(cur, "pasivos_exigibles")),
        "deposit_qoq": _yoy(f(cur, "depositos_totales"), f(prev_q, "depositos_totales")),
        "concentration_pct": _pct(f(cur, "suma_top10"), f(cur, "cartera_bruta")),
    }


def compute_alerts(db: Session, period: Optional[date] = None) -> Dict:
    """Evalúa las 7 alertas por banco en el último período (o *period*). Devuelve el bloque
    del sistema: bancos con banderas activas ordenados por severidad, + resumen por código."""
    from modules.banking_score.models.models import Bank, BankingData

    names = {b.id: b.name for b in db.query(Bank)
             .filter(Bank.is_active.is_(True), Bank.bank_type.in_(MONITORED_TYPES)).all()}
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

    banks: List[Dict] = []
    summary: Dict[str, int] = {}
    for bid, m in metrics.items():
        alerts = evaluate(m, peers)
        if not alerts:
            continue
        for a in alerts:
            summary[a.code] = summary.get(a.code, 0) + 1
        banks.append({
            "bank_id": bid, "name": names.get(bid, bid),
            "max_severity": alerts[0].severity,
            "alerts": [asdict(a) for a in alerts],
        })
    banks.sort(key=lambda b: (b["max_severity"] != "alta", -len(b["alerts"]), b["name"]))
    return {"period": target.isoformat(), "banks": banks, "summary": summary,
            "n_alerts": sum(len(b["alerts"]) for b in banks)}


def bank_alerts(db: Session, bank_id: str) -> Dict:
    """Alertas de UNA entidad al último período (para el deep dive / endpoint por-banco)."""
    block = compute_alerts(db)
    entry = next((b for b in block["banks"] if b["bank_id"] == bank_id), None)
    return {"period": block["period"],
            "alerts": entry["alerts"] if entry else [],
            "max_severity": entry["max_severity"] if entry else None}


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
    for a in alerts:
        lines.append(f"- **{a['label']}** ({a['severity']}) — {a['metric']}: {a['value']} "
                     f"(umbral {a['threshold']}). {a['basis']}.")
    return "\n".join(lines)
