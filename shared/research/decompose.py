"""Descomposición de la pregunta libre en sub-preguntas + mapeo a evidencia.

Determinista por diseño (sin depender del LLM para la garantía de honestidad): parte
la pregunta en cláusulas sustantivas y, por cada una, recupera evidencia con
procedencia del corpus + Data Registry (`shared.knowledge.retrieve`). El estado de
ancla de la sub-pregunta = el mejor que su evidencia soporta (real > rúbrica > brecha).

Un splitter con LLM podría afinar la partición, pero NO cambia la regla dura: cada
sub-pregunta se ancla solo con lo que el retrieval devuelve; lo que no tiene evidencia
se marca brecha (§4).
"""
from __future__ import annotations

import re
from typing import List, Optional

from sqlalchemy.orm import Session

from shared.knowledge.retrieve import retrieve
from shared.registry.signals import GAP, REAL, RUBRIC
from shared.research.models import Evidence, SubQuestion

# Conectores de coordinación donde partir (además de . ? ; y saltos de línea).
_CONNECTORS = re.compile(
    r"\s*(?:[.?;\n]|,?\s+(?:y también|además|asimismo|y además|así como)\s+)\s*",
    re.IGNORECASE,
)
_MIN_TOKENS = 3   # una cláusula con menos que esto no es una sub-pregunta autónoma

# Separador SECUNDARIO: coma+"y"/"e" (A.5 de docs/SPEC_GATE_HONESTIDAD_Y_FUENTES_DGII.md).
# Una "y" simple no parte (rompería enumeraciones "A, B y C"); la coma+"y" solo se parte si la
# cláusula posterior ENCABEZA con un interrogativo → es una segunda PREGUNTA, no una enumeración
# ("A, B, y C" —coma de Oxford— tras ", y" trae un sustantivo, no un interrogativo). El grupo se
# captura para poder RE-UNIR sin distorsionar el texto cuando el corte no procede.
_COMMA_AND = re.compile(r"(,\s+(?:y|e)\s+)", re.IGNORECASE)

# Interrogativos que, al encabezar la cláusula tras ", y"/", e", señalan una segunda pregunta.
# Salvaguarda anti-falso-positivo por ACENTO: 'qué/cómo/cuándo/dónde' (interrogativos) tienen
# homógrafo no-interrogativo sin acento ('que'=relativo, 'como'=comparativo, 'cuando'/'donde'=
# conjunciones) → solo la forma ACENTUADA dispara el corte. Los sin homógrafo ambiguo ('cual',
# 'cuanto'...) se aceptan con o sin acento. Conservador por diseño: ante la duda (interrogativo
# ambiguo escrito sin acento) NO parte y se queda como una sola sub-pregunta (sin regresión).
_INTERROGATIVE_LEAD = frozenset((
    "cual", "cuales", "cuál", "cuáles",
    "cuanto", "cuanta", "cuantos", "cuantas",
    "cuánto", "cuánta", "cuántos", "cuántas",
    "qué", "cómo", "cuándo", "dónde",
))
_LEAD_WORD = re.compile(r"\s*([a-záéíóúñ]+)", re.IGNORECASE)


def _leads_with_interrogative(segment: str) -> bool:
    """¿La cláusula EMPIEZA con un interrogativo (señal de una segunda pregunta)? Se mira el
    primer token conservando acentos: solo así se distingue 'qué/cómo' (pregunta) de 'que/como'
    (relativo/comparativo). Ante la ambigüedad sin acento, devuelve False (no parte)."""
    m = _LEAD_WORD.match(segment or "")
    return bool(m and m.group(1).lower() in _INTERROGATIVE_LEAD)


def _split_compound_and(clause: str) -> List[str]:
    """Parte una cláusula en "X, y Q" SOLO cuando Q (la parte tras ", y"/", e") encabeza con un
    interrogativo — dos preguntas distintas. Una enumeración ("turismo, minería y construcción",
    o con coma de Oxford "turismo, minería, y construcción") trae un sustantivo tras ", y" → NO
    se parte, se re-une con su conector original intacto."""
    tokens = _COMMA_AND.split(clause)
    if len(tokens) == 1:
        return [clause]
    out = [tokens[0]]
    # tokens = [seg0, sep1, seg1, sep2, seg2, …] — separadores en los índices impares.
    for i in range(1, len(tokens) - 1, 2):
        sep, seg = tokens[i], tokens[i + 1]
        if _leads_with_interrogative(seg):
            out.append(seg)                    # corte real → nueva sub-pregunta
        else:
            out[-1] = out[-1] + sep + seg       # enumeración → re-unir sin distorsionar
    return out

# Umbral de ANCLA: un pasaje con score BM25 por debajo de esto NO ancla la sub-pregunta
# —es un roce léxico marginal, no evidencia. Sin él, una pregunta sobre un tópico/entidad
# ausente del corpus (p.ej. "precio del cacao en Marte") se colgaría de cualquier doc que
# comparta vocabulario genérico y fabricaría un ancla por omisión (el modo de fallo del §6).
# [Guessing] Default calibrado sobre el corpus actual (match legítimo ≳8, ruido ≲6); se
# re-calibra con las preguntas reales del piloto (Fase 2), como el umbral del gate (§3.4).
DEFAULT_MIN_ANCHOR_SCORE = 7.0

# Kinds de TEXTO libre (doctrina/metodología/boletín): cruzan un umbral absoluto por
# acumulación de vocabulario genérico más fácil que el dato estructurado (`registry`).
_TEXT_KINDS = ("doctrine", "methodology", "bulletin")

# A4.1 (docs/SPEC_GATE_HONESTIDAD_Y_FUENTES_DGII.md §A.4): barra MÁS ALTA para que un pasaje
# de texto ancle RUBRIC, vs el base de `registry`. Frena el "100% con ancla" falso citando
# doctrina irrelevante. Fijado justo sobre el borde del match legítimo (spec §A.1: "≳8"): un
# pre-filtro barato que descarta el ruido claro; lo dudoso (9-10) lo re-juzga A4.2 (relevancia
# LLM), el backstop real. [Guessing] a calibrar con las 3 preguntas del piloto (regresión).
DEFAULT_MIN_ANCHOR_SCORE_SOFT = 9.0

# A4.3: si la pregunta NO mapeó a ningún eje del catálogo (fuera del alcance de los 14
# ejes), un pasaje de texto necesita una barra AÚN más alta para anclar RUBRIC — o cae a
# GAP. Reusa la señal ya computada por `resolve_targets` (sin llamada nueva).
DEFAULT_MIN_ANCHOR_SCORE_OFFTOPIC = 14.0


def split_question(text: str) -> List[str]:
    """Parte la pregunta en cláusulas sustantivas, deduplicando y preservando orden.

    Dos niveles: (1) conectores duros (. ? ; salto de línea, "y además"…); (2) coma+"y"/"e"
    SOLO si la parte posterior encabeza con un interrogativo — una segunda pregunta, no una
    enumeración (``_split_compound_and``)."""
    parts = _CONNECTORS.split(text or "")
    out: List[str] = []
    seen = set()
    for p in parts:
        for clause in _split_compound_and(p):
            clause = clause.strip(" \t\r\n-·•")
            if len(clause.split()) < _MIN_TOKENS:
                continue
            key = clause.lower()
            if key in seen:
                continue
            seen.add(key)
            out.append(clause)
    # Si no se pudo partir (pregunta corta), la pregunta entera es una sub-pregunta.
    if not out and (text or "").strip():
        out.append(text.strip())
    return out


# Detección de peticiones forward-looking (proyección/escenario a futuro) — que ningún
# motor computa hoy: se declaran como límite, no se rellenan.
_FORWARD_RE = re.compile(
    r"\b(proxim|siguientes?|futur|proyec|pronostic|forecast|escenario|"
    r"shock|estres|stress|a \d+\s*(mes|ano|año)|\d+\s*(meses|anos|años))",
    re.IGNORECASE,
)


def is_forward_looking(text: str) -> bool:
    """¿La pregunta pide una proyección/escenario a futuro (no modelable con el dato de hoy)?"""
    import unicodedata
    norm = "".join(c for c in unicodedata.normalize("NFKD", text.lower())
                   if not unicodedata.combining(c))
    return _FORWARD_RE.search(norm) is not None


# Fuga de código/interno: un pasaje del corpus con rutas de archivo, backticks o muchos
# identificadores snake_case NO debe llegar a un entregable de cliente. Se filtra de la
# evidencia mostrada (sigue en el índice, solo no se cita crudo).
_CODE_RE = re.compile(r"`[^`]+`|[\w/]+\.py\b|\b\w+_\w+_\w+\b|/[a-z_]+/[a-z_]+")


def _is_code_dump(text: str) -> bool:
    return len(_CODE_RE.findall(text or "")) >= 3


def _aggregate_state(evidence: List[Evidence]) -> str:
    """El mejor ancla que la evidencia soporta: real > rúbrica > brecha."""
    if any(e.state == REAL for e in evidence):
        return REAL
    if any(e.state == RUBRIC for e in evidence):
        return RUBRIC
    return GAP


def map_subquestion(text: str, db: Optional[Session], top_k: int = 4,
                    min_anchor_score: float = DEFAULT_MIN_ANCHOR_SCORE,
                    min_anchor_score_soft: float = DEFAULT_MIN_ANCHOR_SCORE_SOFT,
                    question_in_scope: bool = True) -> SubQuestion:
    """Recupera evidencia para *text* y arma la ``SubQuestion`` con estado y ejes.

    Solo cuenta como evidencia (y como ancla) lo que supera ``min_anchor_score``: un
    roce léxico marginal no ancla — la sub-pregunta queda como brecha declarada (§4).

    A4.1/A4.3: la doctrina/metodología (texto libre) debe superar un umbral MÁS ALTO
    (``min_anchor_score_soft``) que el dato estructurado; y si ``question_in_scope`` es
    ``False`` (la pregunta no mapeó a ningún eje del catálogo), la barra sube al umbral
    off-topic. El dato ``registry`` mantiene el base."""
    soft = min_anchor_score_soft if question_in_scope else DEFAULT_MIN_ANCHOR_SCORE_OFFTOPIC
    by_kind = {k: soft for k in _TEXT_KINDS}
    hits = retrieve(text, top_k=top_k, db=db, min_score=min_anchor_score,
                    min_score_by_kind=by_kind)
    # Filtra la fuga de código/interno del corpus antes de que llegue al cliente.
    evidence = [Evidence.from_passage(h) for h in hits if not _is_code_dump(h.get("text", ""))]
    axes: List[str] = []
    for h in hits:
        sk = (h.get("meta") or {}).get("sector_key")
        if sk and sk not in axes:
            axes.append(sk)
    state = _aggregate_state(evidence)
    note = ("" if state != GAP else
            "Sin evidencia con procedencia en el corpus ni en el Data Registry: brecha "
            "declarada (no se completa con conocimiento general del modelo).")
    return SubQuestion(text=text, evidence=evidence, axes=axes, state=state, note=note)


def decompose(question: str, db: Optional[Session] = None, per_q_k: int = 4,
              min_anchor_score: float = DEFAULT_MIN_ANCHOR_SCORE,
              min_anchor_score_soft: float = DEFAULT_MIN_ANCHOR_SCORE_SOFT,
              question_in_scope: bool = True) -> List[SubQuestion]:
    """Descompone la pregunta y mapea cada sub-pregunta a su evidencia con procedencia.

    ``question_in_scope`` (A4.3): lo computa el orquestador desde ``resolve_targets``
    (¿la pregunta mapeó a algún eje del catálogo?) y se propaga al umbral por-kind."""
    return [map_subquestion(clause, db, top_k=per_q_k, min_anchor_score=min_anchor_score,
                            min_anchor_score_soft=min_anchor_score_soft,
                            question_in_scope=question_in_scope)
            for clause in split_question(question)]
