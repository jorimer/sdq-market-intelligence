"""Alerta temprana de pensiones — señales de MONITOREO por AFP para el afiliado/comité.

Las AFP no "fallan" (a diferencia de la banca), así que estas no son precursores de quiebra
sino BANDERAS DE VIGILANCIA sobre el resultado que le importa al afiliado: rentabilidad
rezagada, retorno real negativo (pierde poder adquisitivo), riesgo elevado, costo caro y
erosión de solvencia. Complemento del ISA, no un veredicto.

Reglas PURAS (sin DB) → unit-testables. El orquestador consume el ISA ya computado (que trae
el raw de cada dimensión por AFP), le anexa el retorno real (deflactado BCRD) y la caída de
solvencia interanual, y evalúa por AFP contra percentiles del panel. Umbrales calibrables.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any, Dict, List, Optional

from sqlalchemy.orm import Session

# ── Umbrales (calibrables) ─────────────────────────────────────────────────────
RENTAB_PCTL = 0.20     # rentabilidad bajo el p20 del panel → rezagada
RIESGO_PCTL = 0.80     # σ sobre el p80 del panel → riesgo elevado
COSTO_PCTL = 0.80      # comisión/AUM sobre el p80 del panel → costo elevado
SOLVENCY_DROP = 0.05   # caída interanual de patrimonio/activos ≥ 5% relativo


@dataclass(frozen=True)
class Alert:
    code: str
    label: str
    severity: str          # "alta" | "media"
    value: Optional[float]
    threshold: Optional[float]
    basis: str
    metric: str


def percentile(values: List[float], q: float) -> Optional[float]:
    xs = sorted(v for v in values if v is not None)
    if not xs:
        return None
    if len(xs) == 1:
        return xs[0]
    pos = q * (len(xs) - 1)
    lo = int(pos)
    hi = min(lo + 1, len(xs) - 1)
    return xs[lo] + (xs[hi] - xs[lo]) * (pos - lo)


# ── Reglas puras ───────────────────────────────────────────────────────────────

def rule_rentab(rentab: Optional[float], p20: Optional[float]) -> Optional[Alert]:
    if rentab is None or p20 is None or rentab > p20:
        return None
    return Alert("rentab_rezagada", "Rentabilidad rezagada", "media",
                 round(rentab, 2), round(p20, 2),
                 "Rendimiento nominal en el tramo inferior del panel de AFP",
                 "rentabilidad nominal %")


def rule_real(real: Optional[float]) -> Optional[Alert]:
    if real is None or real >= 0:
        return None
    return Alert("retorno_real_negativo", "Retorno real negativo", "alta",
                 round(real, 2), 0.0,
                 "El retorno deflactado por la inflación del BCRD es negativo: el afiliado "
                 "pierde poder adquisitivo",
                 "rentabilidad real %")


def rule_riesgo(sigma: Optional[float], p80: Optional[float]) -> Optional[Alert]:
    if sigma is None or p80 is None or sigma < p80:
        return None
    return Alert("riesgo_elevado", "Riesgo (volatilidad) elevado", "media",
                 round(sigma, 2), round(p80, 2),
                 "Volatilidad realizada del valor cuota en el tramo superior del panel",
                 "σ anualizada %")


def rule_costo(costo: Optional[float], p80: Optional[float]) -> Optional[Alert]:
    if costo is None or p80 is None or costo < p80:
        return None
    return Alert("costo_elevado", "Costo elevado", "media",
                 round(costo, 3), round(p80, 3),
                 "Comisión sobre AUM en el tramo superior del panel — menor retorno neto",
                 "comisión/AUM %")


def rule_solvency_drop(drop: Optional[float]) -> Optional[Alert]:
    if drop is None or drop < SOLVENCY_DROP:
        return None
    return Alert("caida_solvencia", "Caída de solvencia", "alta",
                 round(drop * 100, 1), SOLVENCY_DROP * 100,
                 "El patrimonio/activos cae de forma material respecto al año anterior",
                 "caída interanual de patrimonio/activos %")


def evaluate(m: Dict, peers: Dict) -> List[Alert]:
    candidates = [
        rule_real(m.get("real")),
        rule_solvency_drop(m.get("solvency_drop")),
        rule_rentab(m.get("rentab"), peers.get("rentab_p20")),
        rule_riesgo(m.get("sigma"), peers.get("riesgo_p80")),
        rule_costo(m.get("costo"), peers.get("costo_p80")),
    ]
    order = {"alta": 0, "media": 1}
    return sorted((a for a in candidates if a is not None), key=lambda a: order.get(a.severity, 9))


# ── Orquestador (consume el ISA + series) ──────────────────────────────────────

def _solvency_drop_by_afp(db: Session) -> Dict[str, float]:
    """Caída interanual del ratio patrimonio/activos por AFP (positiva = deterioro), del
    último punto vs. el de ~12m antes. {} si no hay dos puntos."""
    from modules.pension_intel.validation.backtest import _solvency_by_afp
    out: Dict[str, float] = {}
    for slug, series in _solvency_by_afp(db).items():
        pts = sorted(series.items())
        if len(pts) >= 2:
            prev, cur = pts[-2][1], pts[-1][1]
            if prev:
                out[slug] = (prev - cur) / prev  # >0 = cayó
    return out


def _dim(rating: Dict, key: str) -> Optional[float]:
    d = next((x for x in rating.get("dimensions") or [] if x.get("key") == key), None)
    return d.get("raw") if d else None


def compute_alerts(db: Session) -> Dict[str, Any]:
    """Evalúa las banderas de vigilancia por AFP a partir del ISA + retorno real + caída de
    solvencia. Devuelve el bloque del sistema (AFP con banderas, ordenadas por severidad)."""
    from modules.pension_intel.scoring.isa import annotate_risk_adjusted, compute_isa
    from modules.pension_intel.scoring.real_return import fisher_real, inflation_at
    from shared.contracts import load_inflation_series

    results = compute_isa(db)
    if not results:
        return {"period": None, "afps": [], "summary": {}, "n_alerts": 0}
    infl = load_inflation_series(db)
    drops = _solvency_drop_by_afp(db)

    metrics: Dict[str, Dict] = {}
    for r in results:
        annotate_risk_adjusted(r, db)  # asegura σ en la dim riesgo
        rentab = _dim(r, "rentabilidad")
        i = inflation_at(infl, r.get("period") or "")
        metrics[r["slug"]] = {
            "name": r.get("name"), "slug": r["slug"],
            "rentab": rentab,
            "real": fisher_real(rentab, i) if (rentab is not None and i is not None) else None,
            "sigma": _dim(r, "riesgo"),
            "costo": _dim(r, "costo"),
            "solvency_drop": drops.get(r["slug"]),
        }
    peers = {
        "rentab_p20": percentile([m["rentab"] for m in metrics.values() if m["rentab"] is not None], RENTAB_PCTL),
        "riesgo_p80": percentile([m["sigma"] for m in metrics.values() if m["sigma"] is not None], RIESGO_PCTL),
        "costo_p80": percentile([m["costo"] for m in metrics.values() if m["costo"] is not None], COSTO_PCTL),
    }
    afps: List[Dict] = []
    summary: Dict[str, int] = {}
    for m in metrics.values():
        alerts = evaluate(m, peers)
        if not alerts:
            continue
        for a in alerts:
            summary[a.code] = summary.get(a.code, 0) + 1
        afps.append({"slug": m["slug"], "name": m["name"],
                     "max_severity": alerts[0].severity,
                     "alerts": [asdict(a) for a in alerts]})
    afps.sort(key=lambda a: (a["max_severity"] != "alta", -len(a["alerts"]), a["name"]))
    period = max((r.get("period") for r in results if r.get("period")), default=None)
    return {"period": period, "afps": afps, "summary": summary,
            "n_alerts": sum(len(a["alerts"]) for a in afps)}


def afp_alerts(db: Session, slug: str) -> Dict[str, Any]:
    block = compute_alerts(db)
    entry = next((a for a in block["afps"] if a["slug"] == slug), None)
    return {"period": block["period"],
            "alerts": entry["alerts"] if entry else [],
            "max_severity": entry["max_severity"] if entry else None}


def format_alerts_text(block: Optional[Dict]) -> str:
    """Bloque → texto markdown para la sección del deep dive (determinista, sin IA)."""
    alerts = (block or {}).get("alerts") or []
    if not alerts:
        return ("Sin banderas de vigilancia activas al período. Las señales de monitoreo "
                "(rentabilidad, retorno real, riesgo, costo y solvencia) no se activaron para "
                "esta AFP. Es un complemento del ISA, no un veredicto.")
    lines = ["Banderas de vigilancia activas —señales de monitoreo para el afiliado "
             "(complemento del ISA, no un veredicto):", ""]
    for a in alerts:
        thr = "" if a["threshold"] is None else f" (umbral {a['threshold']})"
        lines.append(f"- **{a['label']}** ({a['severity']}) — {a['metric']}: {a['value']}{thr}. "
                     f"{a['basis']}.")
    return "\n".join(lines)
