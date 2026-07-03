"""Backtest de resultado-proxy del ISA de pensiones — validación soft sobre historia SIPEN.

Ninguna AFP ha fallado, así que no se puede backtestear un default. En su lugar se prueba
la DISCRIMINACIÓN contra un resultado suave — SUBDESEMPEÑO RELATIVO (decisión dueño
2026-07-03): para cada (AFP, período base t), ¿un score BAJO en t ordena a las AFP cuyo
retorno prospectivo cae por debajo de la MEDIANA del panel en la ventana? Dos señales:

  * solvencia — score = patrimonio/activos en t (anual 2010-2026); el núcleo de 35% del ISA
    y la dimensión que backfilleamos. Hipótesis: las AFP menos solventes rinden peor después.
  * rentabilidad — score = rentabilidad_nominal_anual en t (mensual 2003-2026, ~1900 obs);
    chequeo de robustez por persistencia, con N alta → IC estrecho.

Se reporta por señal el Gini + IC bootstrap + calibración por quintiles. Convención (métricas
compartidas): MENOR score = más riesgo (label==1 = subdesempeñó). El caveat de N chico se
declara; si el IC cruza 0 el resultado se marca NO concluyente — nunca se sobre-afirma.

Las funciones de derivación/scoring son PURAS (sin DB) → unit-testables; los loaders leen
``PensionSeries`` y el orquestador arma el reporte que persiste ``operations``/``validation``.
"""
from __future__ import annotations

import statistics
from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple

from sqlalchemy.orm import Session

from shared.validation.metrics import deterioration_rate_by_tier, gini_bootstrap_ci

_QUINTILES = ["Q1 (score más bajo)", "Q2", "Q3", "Q4", "Q5 (score más alto)"]


@dataclass(frozen=True)
class Obs:
    slug: str
    period: str          # período base (YYYY-MM)
    score: float         # menor = más riesgo
    fwd_return: float    # retorno medio prospectivo en la ventana
    label: int           # 1 = subdesempeñó (fwd < mediana del panel en t)


# ── Derivación pura (sin DB) ───────────────────────────────────────────────────

def forward_mean(returns: List[Tuple[str, float]], base: str, horizon: int) -> Optional[float]:
    """Media de los retornos con período ESTRICTAMENTE posterior a *base*, hasta *horizon*
    puntos. None si no hay ninguno. *returns* debe venir ascendente por período."""
    fwd = [v for p, v in returns if p > base][:horizon]
    return statistics.mean(fwd) if fwd else None


def derive_observations(
    score_by_afp: Dict[str, Dict[str, float]],
    returns_by_afp: Dict[str, List[Tuple[str, float]]],
    horizon: int,
    min_afps: int = 3,
) -> List[Obs]:
    """Observaciones etiquetadas por SUBDESEMPEÑO RELATIVO.

    Para cada período base t (unión de los períodos con score), se toma el retorno medio
    prospectivo de cada AFP con score en t; si ≥ *min_afps* tienen dato, se etiqueta 1 a las
    que caen bajo la MEDIANA del panel en ese t. Así la comparación es siempre entre AFP del
    mismo momento (neutral a ciclos comunes de mercado)."""
    periods = sorted({p for s in score_by_afp.values() for p in s})
    out: List[Obs] = []
    for t in periods:
        rows: List[Tuple[str, float, float]] = []  # (slug, score, fwd_return)
        for slug, smap in score_by_afp.items():
            if t not in smap:
                continue
            fwd = forward_mean(returns_by_afp.get(slug, []), t, horizon)
            if fwd is not None:
                rows.append((slug, smap[t], fwd))
        if len(rows) < min_afps:
            continue
        median = statistics.median(r[2] for r in rows)
        for slug, score, fwd in rows:
            out.append(Obs(slug=slug, period=t, score=score, fwd_return=fwd,
                           label=1 if fwd < median else 0))
    return out


def _quintile_tiers(scores: List[float]) -> List[str]:
    """Asigna cada score a un quintil por rango (Q1 = score más bajo = más riesgo). Empates
    comparten quintil; con < 5 valores distintos colapsa proporcionalmente."""
    if not scores:
        return []
    order = sorted(range(len(scores)), key=lambda i: scores[i])
    tiers = [""] * len(scores)
    n = len(order)
    for rank, i in enumerate(order):
        q = min(4, (rank * 5) // n)
        tiers[i] = _QUINTILES[q]
    return tiers


def summarize_signal(obs: List[Obs]) -> Optional[Dict]:
    """Gini + IC bootstrap + calibración por quintil de una señal. None si no hay eventos de
    ambas clases (Gini indefinido). Marca ``conclusive`` = el IC no cruza 0."""
    if len(obs) < 8:
        return None
    scores = [o.score for o in obs]
    labels = [o.label for o in obs]
    if len(set(labels)) < 2:
        return None
    g, lo, hi = gini_bootstrap_ci(scores, labels)
    if g is None:
        return None
    tiers = _quintile_tiers(scores)
    rows, monotonic = deterioration_rate_by_tier(tiers, labels, _QUINTILES)
    conclusive = lo is not None and lo > 0
    return {
        "gini": round(g, 4),
        "gini_ci": [round(lo, 4) if lo is not None else None,
                    round(hi, 4) if hi is not None else None],
        "n_obs": len(obs),
        "n_events": sum(labels),
        "event_rate": round(sum(labels) / len(labels), 4),
        "conclusive": bool(conclusive),
        "monotonic": bool(monotonic),
        "by_quintile": rows,
    }


# ── Loaders (leen PensionSeries) ───────────────────────────────────────────────

def _series_by_afp(db: Session, code: str) -> Dict[str, Dict[str, float]]:
    from modules.pension_intel.models.models import PensionSeries
    rows = (db.query(PensionSeries)
            .filter(PensionSeries.series_code == code,
                    PensionSeries.entity_slug.isnot(None),
                    PensionSeries.value.isnot(None)).all())
    out: Dict[str, Dict[str, float]] = {}
    for r in rows:
        out.setdefault(r.entity_slug, {})[r.period] = float(r.value)
    return out


def _solvency_by_afp(db: Session) -> Dict[str, Dict[str, float]]:
    """patrimonio/activos por AFP y período (solo períodos con ambos)."""
    pat = _series_by_afp(db, "patrimonio")
    act = _series_by_afp(db, "activos_totales")
    out: Dict[str, Dict[str, float]] = {}
    for slug, pmap in pat.items():
        amap = act.get(slug, {})
        for period, p in pmap.items():
            a = amap.get(period)
            if a:
                out.setdefault(slug, {})[period] = p / a
    return out


def _returns_by_afp(db: Session) -> Dict[str, List[Tuple[str, float]]]:
    rmap = _series_by_afp(db, "rentabilidad_nominal_anual")
    return {slug: sorted(v.items()) for slug, v in rmap.items()}


# ── Orquestador ────────────────────────────────────────────────────────────────

def build_backtest_report(db: Session, solvency_horizon: int = 24,
                          return_horizon: int = 12) -> Dict:
    """Corre ambas señales y arma el reporte persistible. Nunca lanza por falta de dato:
    una señal sin poder devolver ``None`` y se declara como tal."""
    returns = _returns_by_afp(db)
    solvency = _solvency_by_afp(db)
    # rentabilidad como score: score(t) = rentabilidad en t; el retorno prospectivo es la
    # misma serie hacia adelante (persistencia).
    return_scores = {slug: {p: v for p, v in lst} for slug, lst in returns.items()}

    signals = {
        "solvency": summarize_signal(derive_observations(solvency, returns, solvency_horizon)),
        "return": summarize_signal(derive_observations(return_scores, returns, return_horizon)),
    }
    computed = any(v is not None for v in signals.values())
    # Gini "de referencia" para G5: la señal concluyente de mayor N; si ninguna concluye, None.
    ranked = sorted(
        [(k, v) for k, v in signals.items() if v and v.get("conclusive")],
        key=lambda kv: kv[1]["n_obs"], reverse=True)
    headline_key, headline = ranked[0] if ranked else (None, None)
    return {
        "computed": computed,
        "outcome": "subdesempeño_relativo",
        "solvency_horizon_m": solvency_horizon,
        "return_horizon_m": return_horizon,
        "signals": signals,
        "headline_gini": headline["gini"] if headline else None,
        "headline_signal": headline_key,
        "note": ("Backtest de resultado-proxy (subdesempeño relativo vs. mediana del panel); "
                 "N por señal limitado por el número de AFP — el IC lo refleja."),
    }
