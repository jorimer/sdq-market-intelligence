"""Resolución de eje + entidad de una pregunta libre (orquestador v2).

El salto de calidad del motor: en vez de solo hacer match léxico contra docs, detecta
QUÉ eje(s) del catálogo toca la pregunta y si nombra una ENTIDAD (un banco, una AFP, una
aseguradora…), para luego traer su dato REAL vía ``snapshot`` (ver ``data_pull``). Sin
esto, una pregunta sobre "Banco Lafise" recuperaba metodología genérica; con esto, ancla
al rating/score/liquidez reales de Lafise.

Determinista y sin importar módulos: las entidades salen del ``scope_options()`` que cada
producto ya expone al catálogo (mismo patrón que el selector del front)."""
from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

from sqlalchemy.orm import Session

from shared.products.registry import PRODUCT_CATALOG, get_product, is_implemented

# Léxico curado por eje (español-neutro, sin acentos). Una pregunta que contenga
# cualquiera de estos términos apunta a ese eje. Curado > inferido: es la señal de
# ruteo, tiene que ser precisa. Ampliable sin tocar lógica.
AXIS_KEYWORDS: Dict[str, Tuple[str, ...]] = {
    "banking": ("banco", "banca", "bancari", "rating", "calificacion", "solidez",
                "liquidez", "mora", "cartera", "solvencia", "eficiencia", "deposito",
                "aeh", "asociacion de ahorro"),
    "macro": ("macro", "inflacion", "pib", "crecimiento", "riesgo pais", "fiscal",
              "deficit", "reservas", "tipo de cambio", "soberano"),
    "monetary_policy": ("politica monetaria", "tpm", "tasa de politica", "tasa de interes",
                        "bcrd tasa", "postura monetaria"),
    "trade": ("comercio exterior", "exportacion", "importacion", "balanza", "arancel",
              "aduana", "socio comercial"),
    "tourism": ("turismo", "turistico", "hotel", "ocupacion", "llegada de turistas"),
    "free_zones": ("zona franca", "zonas francas", "manufactura", "cnzfe", "izf"),
    "energy": ("energia", "energetic", "electric", "generacion", "renovable", "sie", "apagon"),
    "telecom": ("telecom", "telefonia", "internet", "banda ancha", "movil", "penetracion"),
    "construction": ("construccion", "cemento", "permisos de construccion", "vivienda", "obra"),
    "esg": ("esg", "clima", "climatic", "ambiental", "carbono", "resiliencia climatica",
            "adaptacion", "sostenibilidad"),
    "pension": ("pension", "afp", "sipen", "fondo de pension", "cotizante", "rentabilidad afp"),
    "insurance": ("seguro", "aseguradora", "isf", "primas", "siniestralidad", "solvencia aseguradora"),
    "economic_structure": ("estructura de la economia", "estructura economica",
                           "sectores de origen", "valor agregado por sector"),
}

# Términos genéricos que NO distinguen una entidad (evitan matches espurios al resolver
# nombres del roster: "banco", "multiple" aparecen en casi todos los labels bancarios).
_ENTITY_STOPWORDS = frozenset(
    "banco banca multiple ahorro credito servicios sa srl de del la el los las asociacion "
    "aseguradora seguros compania cia fondo afp administradora s a".split())


def _norm(s: str) -> str:
    s = "".join(c for c in unicodedata.normalize("NFKD", s.lower()) if not unicodedata.combining(c))
    return re.sub(r"\s+", " ", s).strip()


def _kw_hit(kw: str, q: str) -> bool:
    """¿El keyword (stem) aparece en *q* en frontera de palabra? Evita falsos positivos
    de substring (p.ej. 'esg' dentro de 'riesgo'). Permite sufijo ('bancari' → bancario)."""
    return re.search(r"\b" + re.escape(kw), q) is not None


def _tokens(s: str) -> List[str]:
    """Tokens alfanuméricos normalizados (sin puntuación)."""
    return re.findall(r"[a-z0-9]+", _norm(s))


@dataclass
class ResolvedEntity:
    sector_key: str
    scope_value: str      # lo que snapshot(scope=…) resuelve (id o nombre)
    label: str            # nombre visible de la entidad
    matched_on: str = ""  # token distintivo que disparó el match


@dataclass
class Targets:
    axes: List[str] = field(default_factory=list)          # ejes detectados (sin entidad)
    entities: List[ResolvedEntity] = field(default_factory=list)

    @property
    def is_empty(self) -> bool:
        return not self.axes and not self.entities


def detect_axes(question: str) -> List[str]:
    """Ejes del catálogo cuyo léxico aparece en la pregunta, en orden del catálogo."""
    q = _norm(question)
    hits: List[str] = []
    for entry in PRODUCT_CATALOG:
        kws = AXIS_KEYWORDS.get(entry.sector_key, ())
        if any(_kw_hit(kw, q) for kw in kws) and entry.sector_key not in hits:
            hits.append(entry.sector_key)
    return hits


def _distinctive_tokens(label: str) -> List[str]:
    """Tokens que identifican una entidad (≥4 chars, no genéricos): 'lafise', 'popular'…"""
    return [t for t in _tokens(label) if len(t) >= 4 and t not in _ENTITY_STOPWORDS]


def resolve_entities(question: str, db: Optional[Session],
                     axes: Optional[List[str]] = None) -> List[ResolvedEntity]:
    """Resuelve entidades nombradas en la pregunta contra el roster ``scope_options()`` de
    los productos (los de *axes* si se da, si no todos los implementados). Match por token
    distintivo (evita colgar de 'banco'/'seguros'). Resiliente por producto."""
    if db is None:
        return []
    q = _norm(question)
    candidates = axes if axes else [e.sector_key for e in PRODUCT_CATALOG]
    out: List[ResolvedEntity] = []
    seen: set = set()
    for sk in candidates:
        if not is_implemented(sk):
            continue
        try:
            product = get_product(sk, db)
            fn = getattr(product, "scope_options", None)
            if not callable(fn):
                continue
            for opt in fn():
                label = str(opt.get("label", ""))
                for tok in _distinctive_tokens(label):
                    if re.search(rf"\b{re.escape(tok)}\b", q):
                        key = (sk, str(opt.get("value")))
                        if key not in seen:
                            seen.add(key)
                            out.append(ResolvedEntity(sector_key=sk, scope_value=str(opt.get("value")),
                                                      label=label, matched_on=tok))
                        break
        except Exception:  # noqa: BLE001 — un roster que falla no rompe la resolución
            if db is not None:
                try:
                    db.rollback()
                except Exception:  # noqa: BLE001
                    pass
    return out


def resolve_targets(question: str, db: Optional[Session]) -> Targets:
    """Ejes detectados + entidades resueltas. Las entidades se buscan primero en los ejes
    detectados; si no hay eje detectado pero sí una entidad, su eje entra igual."""
    axes = detect_axes(question)
    entities = resolve_entities(question, db, axes or None)
    # Un eje con entidad resuelta ya se cubre por la entidad; deja en `axes` solo los
    # ejes SIN entidad (para pull a-nivel-sistema).
    axes_with_entity = {e.sector_key for e in entities}
    axes_only = [a for a in axes if a not in axes_with_entity]
    return Targets(axes=axes_only, entities=entities)
