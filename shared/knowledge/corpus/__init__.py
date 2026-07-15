"""Corpus documental propio de licencia clara — la base de conocimiento del retrieval.

Motor de Research Custom · Fase 3 (docs/SPEC_MOTOR_RESEARCH_CUSTOM.md §3.2/§7).

REGLA DURA DE ALCANCE: aquí SOLO entra material propio ESCRITO PARA SER CITADO A UN CLIENTE.
Dos criterios, ambos obligatorios: (a) derechos claros —material propio de SDQ—, y (b)
audiencia de cliente —prosa curada, no config ni documentación interna de ingeniería—. NUNCA
web abierta scrapeada ni fuente externa nueva (esa sigue el flujo ``shared/source_intel`` con
gate humano). El corpus es un ALLOWLIST explícito (``CORPUS_MANIFEST``), no un barrido de
directorios, para que agregar una fuente sea una decisión revisada, no un accidente.

Hallazgo 7 (2026-07-15): el manifest indexaba specs de arquitectura, bitácoras de PRs y
auditorías internas de ``docs/*.md`` —material propio pero NUNCA escrito para un cliente— y
troceaba los YAML de doctrina completos (pesos, bandas, comentarios de dev). El 89% de los
fragmentos resultaba no apto para cita directa. Corrección: el manifest queda SOLO con la
doctrina, y de ella se extrae ÚNICAMENTE el campo ``rationale`` de cada dimensión/regla —prosa
curada, en español, del tamaño correcto— como un :class:`Passage` citable. NO se trocea el
archivo: los pesos, variables, bandas y demás config los sigue leyendo el motor de scoring
directo del YAML; solo dejan de indexarse para *retrieval*. Una dimensión sin ``rationale`` no
genera pasaje (ausencia de prosa curada = sin cita, nunca dump crudo). El gate de CI
(``tests/test_citability_gate.py``) falla el build si un pasaje contiene tabla/código/config.

El índice léxico (`shared/knowledge/index`) se construye sobre estos pasajes + el Data Registry.
"""
from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import List, Tuple

import yaml

from shared.knowledge.models import (
    KIND_DOCTRINE,
    LICENSE_OWN,
    Passage,
)

_REPO_ROOT = Path(__file__).resolve().parents[3]


@dataclass(frozen=True)
class CorpusSource:
    """Una fuente del corpus: doctrina propia con prosa citable (``rationale``)."""

    path: str            # ruta relativa al repo
    source_label: str    # etiqueta de lineage legible
    kind: str            # KIND_DOCTRINE (hoy el corpus es solo doctrina citable)
    license: str = LICENSE_OWN


# ── El allowlist. SOLO doctrina; de cada archivo se extrae el `rationale` por dimensión/regla.
# Los docs/*.md de metodología/spec salieron en Hallazgo 7 (documentación interna, no cita). ──
CORPUS_MANIFEST: List[CorpusSource] = [
    CorpusSource("shared/doctrine/sectoral.yaml", "Doctrina · Sectorial (IAI)", KIND_DOCTRINE),
    CorpusSource("shared/doctrine/esg.yaml", "Doctrina · ESG/Clima (IRC)", KIND_DOCTRINE),
    CorpusSource("shared/doctrine/regulatory.yaml", "Doctrina · Riesgo regulatorio (IRMP)", KIND_DOCTRINE),
    CorpusSource("shared/doctrine/social.yaml", "Doctrina · Desarrollo social (IDM)", KIND_DOCTRINE),
    CorpusSource("shared/doctrine/macro_sector.yaml", "Doctrina · Contrato macro→sectorial", KIND_DOCTRINE),
]


def _rationales_from_doctrine(data: dict) -> List[Tuple[str, str]]:
    """Extrae ``(clave_dimensión, rationale)`` de una doctrina YA parseada. Dos formas soportadas:

    - ``macro_sector.yaml``: lista ``factors:`` con ``rationale`` inline por regla.
    - ``sectoral``/``esg``/``regulatory``/``social``: mapa ``dimension_rationales:`` {dim: texto}.

    Solo prosa curada: una entrada sin ``rationale`` (o vacío) no genera nada —sin fallback a
    dump crudo del YAML—. El resto del YAML (pesos, variables, bandas, …) NO se toca aquí: lo
    lee el motor de scoring directo (``shared.doctrine.loader``)."""
    out: List[Tuple[str, str]] = []
    factors = data.get("factors")
    if isinstance(factors, list):
        for f in factors:
            if not isinstance(f, dict):
                continue
            r = f.get("rationale")
            if isinstance(r, str) and r.strip():
                key = str(f.get("key") or f.get("label") or f"factor_{len(out)}")
                out.append((key, r.strip()))
    dim_rationales = data.get("dimension_rationales")
    if isinstance(dim_rationales, dict):
        for key, r in dim_rationales.items():
            if isinstance(r, str) and r.strip():
                out.append((str(key), r.strip()))
    return out


def _passages_from_source(src: CorpusSource) -> List[Passage]:
    """Un :class:`Passage` citable por dimensión/regla con ``rationale`` en la fuente. Parseo
    YAML real (no regex sobre texto). Resiliente: archivo ausente o YAML inválido → sin pasajes."""
    path = _REPO_ROOT / src.path
    try:
        text = path.read_text(encoding="utf-8")
    except (FileNotFoundError, OSError):
        return []  # resiliente: una fuente ausente no rompe el corpus
    try:
        data = yaml.safe_load(text)
    except yaml.YAMLError:
        return []
    if not isinstance(data, dict):
        return []
    passages: List[Passage] = []
    for key, rationale in _rationales_from_doctrine(data):
        passages.append(Passage(
            text=rationale, source=src.source_label, kind=src.kind,
            ref=f"{src.path}#{key}", license=src.license,
            meta={"path": src.path, "dimension": key},
        ))
    return passages


@lru_cache(maxsize=1)
def load_corpus_passages() -> tuple:
    """Todos los pasajes del corpus estático (doctrina citable). Cacheado —el corpus solo
    cambia con un deploy. Devuelve tupla (hashable) para el ``lru_cache``."""
    out: List[Passage] = []
    for src in CORPUS_MANIFEST:
        out.extend(_passages_from_source(src))
    return tuple(out)
