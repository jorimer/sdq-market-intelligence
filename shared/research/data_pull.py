"""Pull del resultado real de los motores para una entidad/eje resuelto (orquestador v2).

Le pide a cada motor su resultado YA computado vía ``snapshot`` (Deep Dive → el nivel más
rico; degrada a Insight si hace falta) y lo devuelve como: (a) el ``payload`` crudo —lo que
alimenta al Cerebro como 'datos' para que redacte circunscrito a lo recibido— y (b) unas
líneas de evidencia REAL legibles (cifras clave) para el ancla y el fallback determinista.

Anti-Frankenstein: usa el contrato ``SectorProduct`` del registro; no importa módulos.
Resiliente: una entidad sin dato/ nivel no disponible degrada a brecha, no rompe.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from sqlalchemy.orm import Session

from shared.products.registry import CATALOG_BY_KEY, get_product
from shared.products.tiers import ProductTier
from shared.registry.signals import REAL
from shared.research.models import Evidence
from shared.research.resolve import ResolvedEntity

logger = logging.getLogger("sdq.research.data_pull")


@dataclass
class EnginePull:
    """El resultado de un motor para una entidad: payload crudo + evidencia real."""

    sector_key: str
    entity_label: str
    period: Optional[str]
    source: str                       # fuente autoritativa del eje (catálogo)
    payload: Dict[str, Any] = field(default_factory=dict)
    evidence: List[Evidence] = field(default_factory=list)
    ok: bool = False
    note: str = ""


def _fmt(v: Any) -> str:
    if isinstance(v, (int, float)):
        return f"{v:.1f}" if isinstance(v, float) else str(v)
    return str(v)


def _banking_summary(label: str, payload: Dict[str, Any], period: Optional[str],
                     source: str) -> List[Evidence]:
    """Evidencia REAL legible desde el payload de banca (rating + sub-componentes + pares)."""
    sr = (payload or {}).get("scoring_result") or {}
    if not sr:
        return []
    out: List[Evidence] = []
    tier = sr.get("rating_tier")
    score = sr.get("overall_score")
    head = f"{label}: rating {tier}" if tier else f"{label}"
    if isinstance(score, (int, float)):
        head += f", score global {score:.1f}/100"
    pct = ((sr.get("percentiles") or {}).get("overall"))
    if isinstance(pct, (int, float)):
        head += f" (percentil {pct:.0f} vs el sistema)"
    out.append(Evidence(text=head + f" · período {period or 's/f'}.", source=source,
                        kind="engine", state=REAL, score=100.0))
    sub = sr.get("sub_components") or {}
    if sub:
        parts = ", ".join(f"{k} {_fmt(v)}" for k, v in sub.items())
        out.append(Evidence(text=f"Sub-componentes del rating: {parts}.",
                            source=source, kind="engine", state=REAL, score=99.0))
    peer = payload.get("peer_block") or {}
    if peer.get("cr5") is not None:
        out.append(Evidence(
            text=(f"Concentración del sistema ({peer.get('metric_label','activos')}): "
                  f"CR5 {_fmt(peer.get('cr5'))}, CR10 {_fmt(peer.get('cr10'))}, "
                  f"HHI {_fmt(peer.get('hhi'))}."),
            source=source, kind="engine", state=REAL, score=98.0))
    ew = sr.get("early_warning") or {}
    flags = ew.get("flags") if isinstance(ew, dict) else None
    if flags:
        out.append(Evidence(
            text=f"Alerta temprana: {len(flags)} bandera(s) de monitoreo activa(s) para la entidad.",
            source=source, kind="engine", state=REAL, score=97.0))
    return out


def _generic_summary(label: str, payload: Dict[str, Any], period: Optional[str],
                     source: str) -> List[Evidence]:
    """Evidencia REAL desde cualquier payload: extrae escalares del primer dict con 'score'
    o del nivel superior. Fallback para ejes sin summarizer dedicado (pensiones/seguros/esg)."""
    root = payload or {}
    # Busca un sub-dict de scoring (índice) o usa el top-level.
    cand = None
    for key in ("index", "scoring_result", "score"):
        v = root.get(key)
        if isinstance(v, dict):
            cand = v
            break
    cand = cand or root
    scalars = {k: v for k, v in cand.items() if isinstance(v, (int, float))}
    if not scalars:
        return [Evidence(text=f"{label}: el motor devolvió resultado para el período {period or 's/f'}.",
                        source=source, kind="engine", state=REAL, score=90.0)]
    parts = ", ".join(f"{k} {_fmt(v)}" for k, v in list(scalars.items())[:6])
    return [Evidence(text=f"{label}: {parts} · período {period or 's/f'}.",
                    source=source, kind="engine", state=REAL, score=95.0)]


def pull_entity(db: Optional[Session], resolved: ResolvedEntity) -> EnginePull:
    """Trae el resultado del motor para *resolved* (Deep Dive → Insight → brecha)."""
    entry = CATALOG_BY_KEY.get(resolved.sector_key)
    source = entry.source if entry else resolved.sector_key
    base = EnginePull(sector_key=resolved.sector_key, entity_label=resolved.label,
                      period=None, source=source)
    if db is None:
        base.note = "Sin sesión de datos."
        return base
    product = get_product(resolved.sector_key, db)
    if product is None:
        base.note = "Motor no implementado."
        return base

    for tier in (ProductTier.deep_dive, ProductTier.insight):
        try:
            snap = product.snapshot(tier, "", scope=resolved.scope_value)
        except Exception as e:  # noqa: BLE001 — sin dato para la entidad en ese nivel
            logger.info("snapshot %s/%s (%s) no disponible: %s",
                        resolved.sector_key, tier.value, resolved.label, e)
            try:
                db.rollback()
            except Exception:  # noqa: BLE001
                pass
            continue
        payload = snap.payload or {}
        if resolved.sector_key == "banking":
            ev = _banking_summary(resolved.label, payload, snap.period, source)
        else:
            ev = _generic_summary(resolved.label, payload, snap.period, source)
        return EnginePull(sector_key=resolved.sector_key, entity_label=resolved.label,
                          period=snap.period, source=source, payload=payload,
                          evidence=ev, ok=bool(ev), note="")

    base.note = f"Sin dato del motor para '{resolved.label}' en este período."
    return base
