"""Readiness Audit — evaluación por eje: readiness, cada gate, qué falta y la acción
concreta para cerrarlo.

Reusa el MISMO dato del monitor (``compute_readiness`` + las señales del contrato
``SectorProduct``): no recalcula nada por su cuenta ni inventa cifras. Por cada
sector × nivel reporta el readiness y, por cada gate por debajo del pleno, un
diagnóstico derivado de la señal real (cobertura/frescura/validación) más la acción
concreta para cerrarlo. La acción específica de cada brecha (qué conector, qué
re-sync, qué backtest) vive en un overlay curado declarativo ``_GAP_ACTIONS`` —
guía editorial, no dato fabricado: los números salen todos de las señales reales.

Entregable doble: estructura (para render in-app) + ``markdown`` (documento
exportable). Lo consume ``GET /products/readiness/audit``.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Dict, List

from sqlalchemy.orm import Session

from shared.products.activation import ACTIVATION_THRESHOLD
from shared.products.readiness import GATE_WEIGHTS, _freshness_factor, compute_readiness
from shared.products.registry import PRODUCT_CATALOG, get_product, is_implemented
from shared.products.tiers import ProductTier

logger = logging.getLogger("sdq.products.audit")

GATE_LABELS: Dict[str, str] = {
    "g1": "Datos", "g2": "Motor", "g3": "Narrativa", "g4": "Plantilla", "g5": "Validación",
}
_TIERS = [ProductTier.pulse, ProductTier.insight, ProductTier.deep_dive]
_FULL = 0.999  # un gate ≥ esto se considera pleno (sin brecha)

# Acción concreta por (sector, gate) — guía editorial curada (no dato). Dice CÓMO
# cerrar la brecha cuando el número solo no lo revela (qué conector, qué re-sync, qué
# backtest). Honesta: si la brecha es estructural (no se fabrica), lo dice.
_GAP_ACTIONS: Dict[str, Dict[str, str]] = {
    "tourism": {"g1": "Subir a dato real las 3 variables aún en rúbrica: facilidad de "
                       "negocios y volatilidad regulatoria (Doing Business / serie WGI) e "
                       "índice de competencias (estudios ONE). Cada una sube cobertura → "
                       "cruza 0.85 (Insight/Deep).",
                "g5": "Gate E sectorial diferido: lo desbloquea dato de outcomes por sector, "
                      "no un backtest sobre la base actual."},
    "free_zones": {"g1": "Idéntico a turismo: 3 variables en rúbrica (negocios/competencias/"
                         "volatilidad regulatoria) → su conector cierra la cobertura.",
                   "g5": "Gate E sectorial diferido (outcomes por sector)."},
    "construction": {"g1": "Producto dedicado (ICC): cobertura del MIVHED (permisos) + BCRD "
                          "(PIB construcción). El pipeline solo acredita su peso con ≥4 años "
                          "de permisos (MIVHED desde 2022).",
                     "g5": "Índice preliminar sin backtest de outcomes; sube con validación "
                          "real del ciclo de construcción."},
    "agribusiness": {"g1": "3 variables en rúbrica (negocios/competencias/volatilidad "
                          "regulatoria) → su conector cierra la cobertura.",
                     "g5": "Gate E sectorial diferido (outcomes por sector)."},
    "telecom": {"g1": "Dato INDOTEL congelado: cargar el boletín trimestral más reciente "
                      "(la serie quedó en 2022-Q1). Es la palanca #1: G1=0 hoy.",
                "g5": "Backtest pendiente de una serie con más historia vigente."},
    "energy": {"g1": "Cerrar la brecha de transición energética (cobertura parcial): traer "
                     "las dimensiones faltantes de la matriz SIE/CNE.",
               "g5": "Validación preliminar: subir con outcomes reales del sector."},
    "macro": {"g1": "Re-sync con un período nuevo: la edad del dato IRMP baja solo cuando "
                    "entra el corte siguiente (no es bug, es cadencia).",
              "g5": "Backtest ya fuerte; se refina con más panel/años."},
    "esg": {"g1": "Frescura anual (dato 2023): re-sync al publicarse el corte ND-GAIN/Ember "
                  "siguiente.",
            "g5": "Backtest validado (Spearman significativo); margen menor."},
    "trade": {"g5": "Validación sobre outcomes comerciales: ya en umbral; sube con backtest "
                    "de resiliencia más largo."},
    "pension": {"g5": "Cap ESTRUCTURAL: no hay backtest de quiebras (ninguna AFP quebró). "
                      "Sube con un evento de outcome real o un proxy de validación "
                      "acordado — no se fabrica."},
    "banking": {},
}


def _gate_diagnosis(sector: str, gate: str, value: float, data, val) -> Dict[str, str]:
    """Diagnóstico (qué falta) + acción para un gate por debajo del pleno."""
    action = _GAP_ACTIONS.get(sector, {}).get(gate, "")
    if gate == "g1":
        cov = max(0.0, min(1.0, float(data.coverage)))
        ff = _freshness_factor(data.freshness_days, getattr(data, "cadence", "quarterly"))
        if cov < ff:  # la cobertura es el cuello de botella
            falta = (f"Cobertura {cov:.0%} de la fuente autoritativa: faltan dimensiones "
                     f"con dato real ({data.detail or ', '.join(data.sources)}).")
        else:         # la frescura es el cuello de botella
            edad = "sin fecha" if data.freshness_days is None else f"{data.freshness_days}d"
            falta = (f"Frescura del dato ({edad}, cadencia {getattr(data, 'cadence', '—')}): "
                     f"el último corte quedó rezagado.")
        return {"falta": falta, "accion": action or "Ampliar/actualizar la fuente."}
    if gate == "g2":
        return {"falta": "Motor del índice no operativo para el sector.",
                "accion": action or "Cablear el motor explicable del sector."}
    if gate == "g3":
        return {"falta": "El nivel no declara templates de narrativa.",
                "accion": action or "Declarar los templates del nivel en el manifiesto."}
    if gate == "g4":
        return {"falta": "El nivel no declara secciones para renderizar.",
                "accion": action or "Declarar las secciones del nivel en el manifiesto."}
    # g5
    estado = "no aprobada" if not val.approved else f"parcial (score {val.score:.2f})"
    nota = (val.notes or "sin backtest de outcomes").strip().rstrip(".")
    return {"falta": f"Validación {estado}: {nota}.",
            "accion": action or "Backtest de outcomes / QA firmado del sector."}


def _sector_audit(db: Session, entry) -> Dict[str, Any]:
    sk = entry.sector_key
    if not is_implemented(sk):
        return {"sector_key": sk, "display_name": entry.display_name, "implemented": False,
                "source": entry.source, "readiness": {}, "gaps": [],
                "headline": "Pendiente de cableado: sin producto registrado (readiness 0)."}

    product = get_product(sk, db)
    data = product.data_signals()
    val = product.validation_state()
    reps = {t.value: compute_readiness(product, t) for t in _TIERS}
    pulse = reps[ProductTier.pulse.value]

    # Niveles: readiness vs umbral + publicabilidad.
    levels = []
    for t in _TIERS:
        rep = reps[t.value]
        thr = ACTIVATION_THRESHOLD[t]
        levels.append({"tier": t.value, "readiness": rep["readiness"], "threshold": thr,
                       "can_publish": rep["readiness"] >= thr})

    # Brechas a nivel sector — desde los gates del Pulse (g1/g2/g5 son del sector; g3/g4
    # del nivel, plenos en todos los ejes cableados). Ranqueadas por puntos de readiness
    # perdidos (peso × déficit) = el orden de las palancas de mayor retorno.
    gaps: List[Dict[str, Any]] = []
    for gate in ("g1", "g2", "g3", "g4", "g5"):
        value = float(pulse[gate])
        if value >= _FULL:
            continue
        diag = _gate_diagnosis(sk, gate, value, data, val)
        gaps.append({
            "gate": gate, "label": GATE_LABELS[gate], "value": round(value, 4),
            "weight": GATE_WEIGHTS[gate],
            "points_lost": round(GATE_WEIGHTS[gate] * (1.0 - value), 4),
            "lineage": pulse["detail"].get(gate, ""),
            "falta": diag["falta"], "accion": diag["accion"],
        })
    gaps.sort(key=lambda g: g["points_lost"], reverse=True)

    top = gaps[0] if gaps else None
    if top is None:
        headline = "Listo (full): los 5 gates en pleno; publicable en los 3 niveles."
    else:
        levers = " · ".join(f"{g['label']} ({g['value']:.0%})" for g in gaps[:2])
        headline = f"Palanca: {levers}. {top['accion']}"

    return {"sector_key": sk, "display_name": entry.display_name, "implemented": True,
            "source": entry.source, "readiness": {k: v["readiness"] for k, v in reps.items()},
            "levels": levels, "gaps": gaps, "headline": headline}


def _safe_sector_audit(db: Session, entry) -> Dict[str, Any]:
    """``_sector_audit`` resiliente: una lectura que falla (tabla ausente, transacción
    abortada) degrada SOLO ese sector, sin tumbar el audit completo. La sesión se
    revierte para que el siguiente sector no herede una transacción rota (Postgres)."""
    try:
        return _sector_audit(db, entry)
    except Exception as e:  # noqa: BLE001
        logger.warning("Audit de '%s' no disponible: %s", entry.sector_key, e)
        try:
            db.rollback()
        except Exception:  # noqa: BLE001
            pass
        return {"sector_key": entry.sector_key, "display_name": entry.display_name,
                "implemented": is_implemented(entry.sector_key), "source": entry.source,
                "readiness": {}, "levels": [], "gaps": [],
                "headline": "No evaluable ahora (señal del sector no disponible)."}


def build_audit(db: Session) -> Dict[str, Any]:
    """Readiness Audit completo (estructura + markdown). Mismo dato que el monitor."""
    sectors = [_safe_sector_audit(db, e) for e in PRODUCT_CATALOG]
    thresholds = {t.value: v for t, v in ACTIVATION_THRESHOLD.items()}

    def _bucket(s: Dict[str, Any]) -> str:
        if not s["implemented"]:
            return "pending"
        lv = {lev["tier"]: lev for lev in s.get("levels", [])}
        if not lv:  # implementado pero degradado (sin niveles evaluables)
            return "blocked"
        if all(lv[t]["can_publish"] for t in lv):
            return "full"
        if lv.get("pulse", {}).get("can_publish"):
            return "pulse_only"
        return "blocked"

    summary = {"full": [], "pulse_only": [], "blocked": [], "pending": []}
    for s in sectors:
        summary[_bucket(s)].append(s["sector_key"])

    generated_at = datetime.now(timezone.utc).isoformat()
    audit = {"generated_at": generated_at, "thresholds": thresholds,
             "summary": summary, "sectors": sectors}
    audit["markdown"] = render_audit_markdown(audit)
    return audit


def render_audit_markdown(audit: Dict[str, Any]) -> str:
    """Documento markdown del audit (exportable). Determinista desde la estructura."""
    thr = audit["thresholds"]
    fecha = audit["generated_at"][:10]
    sm = audit["summary"]
    out: List[str] = []
    out.append("# SDQ·MIP — Readiness Audit")
    out.append(f"\n_Generado {fecha} · umbrales: Pulse {thr['pulse']:.2f} · "
               f"Insight {thr['insight']:.2f} · Deep Dive {thr['deep_dive']:.2f}_\n")
    out.append("Readiness = G1 Datos (30%) · G2 Motor (25%) · G3 Narrativa (15%) · "
               "G4 Plantilla (15%) · G5 Validación (15%).\n")

    out.append("## Resumen\n")
    out.append(f"- **Full (3 niveles publicables):** {', '.join(sm['full']) or '—'}")
    out.append(f"- **Solo Pulse:** {', '.join(sm['pulse_only']) or '—'}")
    out.append(f"- **Bloqueado (ni Pulse):** {', '.join(sm['blocked']) or '—'}")
    out.append(f"- **Pendiente de cableado:** {', '.join(sm['pending']) or '—'}\n")

    # Sectores ordenados por readiness Pulse descendente (los más listos primero).
    def _key(s: Dict[str, Any]) -> float:
        return (s.get("readiness") or {}).get("pulse", 0.0)
    for s in sorted(audit["sectors"], key=_key, reverse=True):
        out.append(f"## {s['display_name']} (`{s['sector_key']}`)\n")
        if not s["implemented"] or not s.get("readiness"):
            out.append(f"_{s['headline']}_\n")
            continue
        r = s["readiness"]
        out.append(f"**Readiness** — Pulse {r['pulse']:.3f} · Insight {r['insight']:.3f} · "
                   f"Deep Dive {r['deep_dive']:.3f}")
        pub = [lev["tier"] for lev in s["levels"] if lev["can_publish"]]
        out.append(f"**Publicable:** {', '.join(pub) if pub else 'ninguno'}  ·  "
                   f"_{s['headline']}_\n")
        if not s["gaps"]:
            out.append("Sin brechas: los 5 gates en pleno.\n")
            continue
        out.append("| Gate | Valor | Peso | Puntos perdidos | Qué falta | Acción |")
        out.append("|---|---|---|---|---|---|")
        for g in s["gaps"]:
            out.append(f"| {g['label']} ({g['gate'].upper()}) | {g['value']:.0%} | "
                       f"{g['weight']:.0%} | {g['points_lost']:.3f} | {g['falta']} | "
                       f"{g['accion']} |")
        out.append("")
    return "\n".join(out)
