"""Ingesta — arma la colección de pasajes y construye el índice léxico.

Motor de Research Custom · Fase 3 (docs/SPEC_MOTOR_RESEARCH_CUSTOM.md §3.2).

Dos fuentes de pasajes, ambas de procedencia clara:
  (a) el corpus documental estático (``shared/knowledge/corpus`` — doctrina + metodología);
  (b) el Data Registry vivo (``shared/registry`` — qué mide cada eje, con qué dato real).

El corpus (a) solo cambia con un deploy → se cachea. El registro (b) refleja el estado
de los datos hoy → se re-ingiere por consulta cuando se pasa una sesión de DB. Fusionar
ambos es lo que permite al retrieval contestar tanto "¿cómo mide SDQ el riesgo X?"
(metodología) como "¿tenemos dato real de X hoy?" (registro).
"""
from __future__ import annotations

import logging
from functools import lru_cache
from typing import List, Optional

from sqlalchemy.orm import Session

from shared.knowledge.corpus import load_corpus_passages
from shared.knowledge.index import LexicalIndex
from shared.knowledge.models import (
    KIND_REGISTRY,
    LICENSE_OWN,
    LICENSE_PUBLIC,
    Passage,
)

logger = logging.getLogger("sdq.knowledge.ingest")

_STATE_ES = {"real": "dato real", "rubric": "rúbrica declarada", "gap": "brecha declarada"}


def registry_passages(db: Optional[Session]) -> List[Passage]:
    """Pasajes derivados del Data Registry vivo: uno-resumen por eje + uno por variable
    con su procedencia. ``[]`` si el registro no está disponible (degrada, no rompe)."""
    if db is None:
        return []
    try:
        from shared.registry.service import build_data_registry
        reg = build_data_registry(db)
    except Exception as e:  # noqa: BLE001
        logger.warning("Data Registry no disponible para ingesta: %s", e)
        return []

    out: List[Passage] = []
    for a in reg.axes:
        if not a.implemented:
            continue
        counts = a.state_counts
        out.append(Passage(
            text=(f"Eje '{a.display_name}' ({a.sector_key}). Fuente autoritativa: "
                  f"{a.source}. Mide {len(a.signals)} variables; cobertura de dato real "
                  f"{a.coverage_real:.0%}. Reales: {counts['real']} · "
                  f"rúbrica: {counts['rubric']} · brecha: {counts['gap']}."
                  + (f" {a.note}" if a.note else "")),
            source=f"Data Registry · {a.display_name}", kind=KIND_REGISTRY,
            ref=f"registry/{a.sector_key}", license=LICENSE_OWN,
            meta={"sector_key": a.sector_key, "coverage_real": a.coverage_real},
        ))
        for s in a.signals:
            estado = _STATE_ES.get(s.state, s.state)
            lineage = s.source or a.source
            frac = f" (cobertura parcial {s.real_fraction:.0%})" if (
                s.state == "real" and s.real_fraction < 0.999) else ""
            out.append(Passage(
                text=(f"Variable '{s.label}' ({s.key}) del eje {a.display_name}"
                      + (f", dimensión {s.dimension}" if s.dimension else "")
                      + f". Estado: {estado}{frac}. "
                      + (f"Fuente: {lineage}. Cadencia: {s.cadence}. " if s.state == "real"
                         else "")
                      + (f"Nota: {s.note}." if s.note else "")),
                source=(f"Data Registry · {a.display_name} · {lineage}"
                        if s.state == "real" else f"Data Registry · {a.display_name}"),
                kind=KIND_REGISTRY,
                ref=f"registry/{a.sector_key}/{s.key}",
                license=LICENSE_PUBLIC if s.state == "real" else LICENSE_OWN,
                meta={"sector_key": a.sector_key, "variable": s.key, "state": s.state,
                      "weight": s.weight, "real_fraction": s.real_fraction,
                      # La proyección viaja con la señal: es el primero de los tres puntos
                      # del cableado. Sin esto, la evidencia llega proyectada pero sin nada
                      # que el gate pueda juzgar, y una proyección sin metadato no ancla.
                      "projection": s.projection},
            ))
    return out


def dgii_passages(db: Optional[Session]) -> List[Passage]:
    """Pasajes del padrón de contribuyentes DGII (§B): un pasaje por vertical del crosswalk,
    con el conteo de activos del corte más reciente, la fecha de corte y el caveat obligatorio.
    ``kind="registry"`` + ``meta.state="real"`` → ``_evidence_state`` lo trata REAL. ``[]`` si
    no hay DB o el padrón no se cargó (degrada, no rompe)."""
    if db is None:
        return []
    try:
        from shared.data.dgii_rnc_client import CAVEAT, PAGE_URL, VERTICALS
        from shared.reference.dgii_query import latest_contribuyentes
        corte, by_code = latest_contribuyentes(db)
    except Exception as e:  # noqa: BLE001 — tabla ausente / import → sin pasajes DGII
        logger.warning("Padrón DGII no disponible para ingesta: %s", e)
        return []
    if corte is None or not by_code:
        return []

    fecha = corte.strftime("%d/%m/%Y")
    out: List[Passage] = []
    for v in VERTICALS:
        total = sum(r.activos or 0 for code, r in by_code.items() if v.matches(code))
        if total <= 0:
            continue
        total_str = f"{total:,}".replace(",", ".")   # separador de miles es-DO
        scope = f" {v.scope_note}." if v.scope_note else ""
        out.append(Passage(
            text=(f"Contribuyentes activos registrados en la DGII para {v.label} "
                  f"({v.terms}) — CIIU {v.code_label}: {total_str} al corte {fecha}.{scope} {CAVEAT}"),
            source="DGII · Estadísticas de Contribuyentes por Actividad Económica",
            kind=KIND_REGISTRY,
            ref=f"dgii/contribuyentes/{v.key}",
            license=LICENSE_PUBLIC,
            meta={"state": "real", "corte": corte.isoformat(), "vertical": v.key,
                  "subclases": list(v.codes) or [f"{v.prefix}xxx"],
                  "caveat": CAVEAT, "source_url": PAGE_URL},
        ))
    return out


@lru_cache(maxsize=1)
def _corpus_index() -> LexicalIndex:
    """Índice solo-corpus (estático), cacheado — sirve para consultas sin DB."""
    return LexicalIndex(load_corpus_passages())


def build_passages(db: Optional[Session] = None,
                   include_registry: bool = True) -> List[Passage]:
    """Colección completa: corpus estático + (opcional) Data Registry vivo."""
    passages = list(load_corpus_passages())
    if include_registry:
        passages.extend(registry_passages(db))
        passages.extend(dgii_passages(db))
    return passages


def build_index(db: Optional[Session] = None,
                include_registry: bool = True) -> LexicalIndex:
    """Índice léxico sobre corpus (+ registro vivo si hay DB). Sin DB reutiliza el
    índice de corpus cacheado; con DB reconstruye (el registro es chico, ~cientos de
    pasajes)."""
    if db is None or not include_registry:
        return _corpus_index()
    return LexicalIndex(build_passages(db, include_registry=True))
