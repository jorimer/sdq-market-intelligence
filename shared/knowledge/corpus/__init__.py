"""Corpus documental propio de licencia clara — la base de conocimiento del retrieval.

Motor de Research Custom · Fase 3 (docs/SPEC_MOTOR_RESEARCH_CUSTOM.md §3.2/§7).

REGLA DURA DE ALCANCE: aquí SOLO entra material propio o de derechos claros —doctrina
versionada y documentos de metodología de SDQ—. NUNCA web abierta scrapeada ni fuente
externa nueva (esa sigue el flujo ``shared/source_intel`` con gate humano). El corpus
es un ALLOWLIST explícito (``CORPUS_MANIFEST``), no un barrido de directorios, para que
agregar una fuente sea una decisión revisada, no un accidente.

Cada documento se trocea en :class:`Passage` con su lineage adjunto. El índice léxico
(`shared/knowledge/index`) se construye sobre estos pasajes + los del Data Registry.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import List

from shared.knowledge.models import (
    KIND_DOCTRINE,
    KIND_METHODOLOGY,
    LICENSE_OWN,
    Passage,
)

_REPO_ROOT = Path(__file__).resolve().parents[3]

# Tamaño objetivo de un pasaje troceado (caracteres). Bloques más chicos se fusionan;
# más grandes se cortan en límite de párrafo. Compromiso recuperación/legibilidad.
_CHUNK_TARGET = 700
_CHUNK_MAX = 1100


@dataclass(frozen=True)
class CorpusSource:
    """Una fuente del corpus (documento propio de derechos claros)."""

    path: str            # ruta relativa al repo
    source_label: str    # etiqueta de lineage legible
    kind: str            # KIND_DOCTRINE | KIND_METHODOLOGY
    license: str = LICENSE_OWN


# ── El allowlist. Solo metodología/doctrina propia. Ampliar es una decisión revisada. ──
CORPUS_MANIFEST: List[CorpusSource] = [
    # Doctrina versionada (pesos + rúbrica declarada por eje).
    CorpusSource("shared/doctrine/sectoral.yaml", "Doctrina · Sectorial (IAI)", KIND_DOCTRINE),
    CorpusSource("shared/doctrine/esg.yaml", "Doctrina · ESG/Clima (IRC)", KIND_DOCTRINE),
    CorpusSource("shared/doctrine/regulatory.yaml", "Doctrina · Riesgo regulatorio (IRMP)", KIND_DOCTRINE),
    CorpusSource("shared/doctrine/social.yaml", "Doctrina · Desarrollo social (IDM)", KIND_DOCTRINE),
    CorpusSource("shared/doctrine/macro_sector.yaml", "Doctrina · Contrato macro→sectorial", KIND_DOCTRINE),
    # Metodología / estándar propio.
    CorpusSource("docs/REPORT_STANDARD.md", "Metodología · Estándar de Reporte MIR", KIND_METHODOLOGY),
    CorpusSource("docs/DEEP_DIVE_FITCH_PARITY.md", "Metodología · Paridad Deep Dive vs Fitch", KIND_METHODOLOGY),
    CorpusSource("docs/RUBRIC_AUDIT_AND_REMEDIATION.md", "Metodología · Auditoría de rúbricas", KIND_METHODOLOGY),
    CorpusSource("docs/IRMP_SOURCE_UPGRADE_RESEARCH.md", "Metodología · Fuentes del IRMP", KIND_METHODOLOGY),
    CorpusSource("docs/SPEC_PLATFORM_PRODUCTIZATION.md", "Metodología · Productización de plataforma", KIND_METHODOLOGY),
    CorpusSource("docs/SPEC_TIER_PRODUCTIZATION_BANKING.md", "Metodología · Tiers Banking", KIND_METHODOLOGY),
    CorpusSource("docs/RECETA_ONBOARDING_SECTOR.md", "Metodología · Onboarding de sector", KIND_METHODOLOGY),
    CorpusSource("docs/SERIES_CANONICAS_BCRD.md", "Referencia · Series canónicas BCRD", KIND_METHODOLOGY),
    CorpusSource("docs/bcrd_estadisticas_catalog.md", "Referencia · Catálogo estadístico BCRD", KIND_METHODOLOGY),
    CorpusSource("docs/sectorial-gate-e-data-spec.md", "Metodología · Gate E sectorial (datos)", KIND_METHODOLOGY),
]


def _split_blocks(text: str) -> List[str]:
    """Trocea por párrafos (líneas en blanco), fusionando hacia ``_CHUNK_TARGET`` y
    cortando en ``_CHUNK_MAX``. Determinista — sin dependencias externas."""
    raw = [b.strip() for b in re.split(r"\n\s*\n", text) if b.strip()]
    out: List[str] = []
    buf = ""
    for block in raw:
        if len(block) > _CHUNK_MAX:  # bloque enorme (tabla, lista larga): cortar duro
            if buf:
                out.append(buf)
                buf = ""
            for i in range(0, len(block), _CHUNK_MAX):
                out.append(block[i:i + _CHUNK_MAX])
            continue
        if not buf:
            buf = block
        elif len(buf) + len(block) + 2 <= _CHUNK_TARGET:
            buf += "\n\n" + block
        else:
            out.append(buf)
            buf = block
    if buf:
        out.append(buf)
    return out


def _passages_from_source(src: CorpusSource) -> List[Passage]:
    path = _REPO_ROOT / src.path
    try:
        text = path.read_text(encoding="utf-8")
    except (FileNotFoundError, OSError):
        return []  # resiliente: una fuente ausente no rompe el corpus
    passages: List[Passage] = []
    for i, block in enumerate(_split_blocks(text)):
        passages.append(Passage(
            text=block, source=src.source_label, kind=src.kind,
            ref=f"{src.path}#{i}", license=src.license,
            meta={"path": src.path, "chunk": i},
        ))
    return passages


@lru_cache(maxsize=1)
def load_corpus_passages() -> tuple:
    """Todos los pasajes del corpus estático (doctrina + metodología). Cacheado —el
    corpus solo cambia con un deploy. Devuelve tupla (hashable) para el ``lru_cache``."""
    out: List[Passage] = []
    for src in CORPUS_MANIFEST:
        out.extend(_passages_from_source(src))
    return tuple(out)
