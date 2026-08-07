"""Backtest de resultado-proxy del ISF de seguros — validación soft sobre historia SIS.

Ninguna aseguradora del mercado ha quebrado en la ventana, así que no se puede backtestear
un default. Se prueba la DISCRIMINACIÓN contra un resultado suave — SUBDESEMPEÑO RELATIVO
(mismo método que el ISA de pensiones): para cada (aseguradora, año base t), ¿un score BAJO
en t ordena a las aseguradoras cuyo desempeño prospectivo cae por debajo de la MEDIANA del
panel? Dos señales, sobre los estados financieros auditados por compañía (anual 2018-):

  * solvencia    — score = patrimonio/activos en t; forward = la misma serie (persistencia
    de la fortaleza de capital). Núcleo de 35% del ISF.
  * underwriting — score = resultado técnico ((ingresos−gastos)/primas) en t; forward = la
    misma serie (persistencia de la rentabilidad técnica).

Ventaja frente a pensiones: ~33 aseguradoras × varios años → N mucho mayor, IC más estrecho.
Convención (métricas compartidas): MENOR score = más riesgo (label==1 = subdesempeñó). El
caveat de N se declara; si el IC cruza 0 el resultado se marca NO concluyente — nunca se
sobre-afirma. Derivación PURA (sin DB) → unit-testable; loaders leen ``InsuranceSeries``.
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
    period: str
    score: float          # menor = más riesgo
    fwd: float            # desempeño medio prospectivo
    label: int            # 1 = subdesempeñó (fwd < mediana del panel en t)


# ── Derivación pura (sin DB) ───────────────────────────────────────────────────

def forward_mean(series: List[Tuple[str, float]], base: str, horizon: int) -> Optional[float]:
    """Media de los valores con período ESTRICTAMENTE posterior a *base*, hasta *horizon*.
    None si no hay ninguno. *series* asc por período."""
    fwd = [v for p, v in series if p > base][:horizon]
    return statistics.mean(fwd) if fwd else None


def derive_observations(
    score_by: Dict[str, Dict[str, float]],
    fwd_by: Dict[str, List[Tuple[str, float]]],
    horizon: int,
    min_entities: int = 5,
) -> List[Obs]:
    """Observaciones etiquetadas por SUBDESEMPEÑO RELATIVO. Para cada año base t, se toma el
    desempeño medio prospectivo de cada aseguradora con score en t; si ≥ *min_entities* tienen
    dato, se etiqueta 1 a las que caen bajo la MEDIANA del panel en ese t (comparación entre
    pares del mismo momento → neutral a ciclos comunes)."""
    periods = sorted({p for s in score_by.values() for p in s})
    out: List[Obs] = []
    for t in periods:
        rows: List[Tuple[str, float, float]] = []
        for slug, smap in score_by.items():
            if t not in smap:
                continue
            f = forward_mean(fwd_by.get(slug, []), t, horizon)
            if f is not None:
                rows.append((slug, smap[t], f))
        if len(rows) < min_entities:
            continue
        median = statistics.median(r[2] for r in rows)
        for slug, score, f in rows:
            out.append(Obs(slug=slug, period=t, score=score, fwd=f,
                           label=1 if f < median else 0))
    return out


def _quintile_tiers(scores: List[float]) -> List[str]:
    if not scores:
        return []
    order = sorted(range(len(scores)), key=lambda i: scores[i])
    tiers = [""] * len(scores)
    n = len(order)
    for rank, i in enumerate(order):
        tiers[i] = _QUINTILES[min(4, (rank * 5) // n)]
    return tiers


def summarize_signal(obs: List[Obs]) -> Optional[Dict]:
    """Gini + IC bootstrap + calibración por quintil. None si no hay eventos de ambas clases.
    ``conclusive`` = el IC no cruza 0."""
    if len(obs) < 8:
        return None
    scores = [o.score for o in obs]
    labels = [o.label for o in obs]
    if len(set(labels)) < 2:
        return None
    g, lo, hi = gini_bootstrap_ci(scores, labels)
    if g is None:
        return None
    rows, monotonic = deterioration_rate_by_tier(_quintile_tiers(scores), labels, _QUINTILES)
    conclusive = lo is not None and lo > 0
    return {
        "gini": round(g, 4),
        "gini_ci": [round(lo, 4) if lo is not None else None,
                    round(hi, 4) if hi is not None else None],
        "n_obs": len(obs), "n_events": sum(labels),
        "event_rate": round(sum(labels) / len(labels), 4),
        "conclusive": bool(conclusive), "monotonic": bool(monotonic),
        "by_quintile": rows,
    }


# ── Loaders (leen InsuranceSeries por entidad) ─────────────────────────────────

def _series_by_insurer(db: Session, code: str) -> Dict[str, Dict[str, float]]:
    from modules.insurance_intel.models.models import InsuranceSeries
    rows = (db.query(InsuranceSeries)
            .filter(InsuranceSeries.series_code == code,
                    InsuranceSeries.entity_slug.isnot(None),
                    InsuranceSeries.value.isnot(None)).all())
    out: Dict[str, Dict[str, float]] = {}
    for r in rows:
        out.setdefault(r.entity_slug, {})[r.period] = float(r.value)
    return out


def _ratio_by_insurer(db: Session, num_code: str, den_code: str) -> Dict[str, Dict[str, float]]:
    num = _series_by_insurer(db, num_code)
    den = _series_by_insurer(db, den_code)
    out: Dict[str, Dict[str, float]] = {}
    for slug, nmap in num.items():
        dmap = den.get(slug, {})
        for period, n in nmap.items():
            d = dmap.get(period)
            if d:
                out.setdefault(slug, {})[period] = n / d
    return out


def _solvency_by_insurer(db: Session) -> Dict[str, Dict[str, float]]:
    return _ratio_by_insurer(db, "patrimonio", "activos_totales")


def _underwriting_by_insurer(db: Session) -> Dict[str, Dict[str, float]]:
    """Margen técnico = 1 − combined ratio, por aseguradora y año.

    Misma definición que ``isf._raw_metric('resultado_tecnico')`` — antes replicaba aquí la
    fórmula ``(ingresos − gastos) / primas``, que contaba los siniestros dos veces (la
    sección 5 del catálogo SIS los incluye). Un período sin ``gastos_operativos`` ingerido
    queda FUERA del backtest en vez de reconstruirse con la fórmula vieja: validar contra
    una métrica defectuosa es peor que validar contra menos períodos.
    """
    sin = _series_by_insurer(db, "siniestros_pagados")
    gop = _series_by_insurer(db, "gastos_operativos")
    pri = _series_by_insurer(db, "primas_suscritas")
    out: Dict[str, Dict[str, float]] = {}
    for slug, smap in sin.items():
        gmap, pmap = gop.get(slug, {}), pri.get(slug, {})
        for period, s in smap.items():
            g, p = gmap.get(period), pmap.get(period)
            if s is not None and g is not None and p:
                out.setdefault(slug, {})[period] = 1.0 - (s + g) / p
    return out


def _as_series(by: Dict[str, Dict[str, float]]) -> Dict[str, List[Tuple[str, float]]]:
    return {slug: sorted(m.items()) for slug, m in by.items()}


# ── Orquestador ────────────────────────────────────────────────────────────────

def build_backtest_report(db: Session, horizon: int = 3) -> Dict:
    """Corre ambas señales y arma el reporte persistible. El OUTCOME prospectivo es el
    resultado técnico (P&L de suscripción) en ambas — así la señal de solvencia es CRUZADA
    (¿la fortaleza de capital en t ordena el subdesempeño técnico futuro?), no una mera
    autocorrelación, y la de underwriting mide persistencia. Nunca lanza por falta de dato."""
    solvency = _solvency_by_insurer(db)
    underwriting = _underwriting_by_insurer(db)
    fwd = _as_series(underwriting)  # outcome común: resultado técnico prospectivo

    signals = {
        "solvency": summarize_signal(derive_observations(solvency, fwd, horizon)),
        "underwriting": summarize_signal(derive_observations(underwriting, fwd, horizon)),
    }
    computed = any(v is not None for v in signals.values())
    ranked = sorted([(k, v) for k, v in signals.items() if v and v.get("conclusive")],
                    key=lambda kv: kv[1]["n_obs"], reverse=True)
    headline_key, headline = ranked[0] if ranked else (None, None)
    return {
        "computed": computed,
        "outcome": "subdesempeño_relativo",
        "horizon_y": horizon,
        "signals": signals,
        "headline_gini": headline["gini"] if headline else None,
        "headline_signal": headline_key,
        "note": ("Backtest de resultado-proxy (subdesempeño relativo vs. mediana del panel) "
                 "sobre estados financieros auditados por compañía; persistencia a "
                 f"{horizon} años. N por señal = aseguradoras × años."),
    }
