"""Gate de citabilidad del corpus (Hallazgo 7).

Ningún ``Passage`` del corpus puede contener material no apto para cita directa a un cliente:
fence de código, tabla markdown, dump de config ``key: value``, o densidad de identificadores/
rutas de código. Es la generalización PERMANENTE del script de auditoría del diagnóstico
(Hallazgo 7 §1/§4): si alguien agrega una fuente no citable al ``CORPUS_MANIFEST`` o un
``rationale`` de doctrina mal escrito, el BUILD falla acá — no lo descubre un cliente en un PDF.

Combina con el fix de Hallazgo 5 (round-robin por fuente en ``_evidence_lines``): cualquier
fuente que llegue a ``sq.evidence`` ya pasó este gate en la ingesta, no depende de que la
truncación la esconda.
"""
import re

from shared.knowledge.corpus import load_corpus_passages
from shared.knowledge.retrieve import retrieve
from shared.research.decompose import _CODE_RE  # reuso: densidad de identificadores/rutas

# Una línea de config ``clave: valor`` (minúsculas/guion_bajo). ≥4 de estas sin prosa que las
# cierre = dump de YAML/config, no cita.
_KEY_LINE = re.compile(r"^\s*[a-z_]+:\s")
# Una "frase de cierre": una palabra de prosa terminada en puntuación de oración. Su ausencia,
# junto a muchas líneas ``key:``, delata un bloque de config sin prosa.
_CLOSING_PHRASE = re.compile(r"[a-záéíóúñ]{3,}[.!?]")


def _citability_violations(text: str) -> list:
    """Razones por las que *text* NO es apto para cita directa a cliente (vacío = apto)."""
    reasons = []
    lines = text.splitlines()
    if "```" in text:
        reasons.append("fence de código (```)")
    if sum(1 for ln in lines if ln.count("|") >= 2) >= 2:
        reasons.append("≥2 filas de tabla markdown (líneas con ≥2 '|')")
    key_lines = sum(1 for ln in lines if _KEY_LINE.match(ln))
    if key_lines >= 4 and not _CLOSING_PHRASE.search(text):
        reasons.append(f"dump de config: {key_lines} líneas 'clave:' sin prosa de cierre")
    n_code = len(_CODE_RE.findall(text))
    if n_code >= 3:
        reasons.append(f"densidad de identificadores/rutas de código: {n_code} (≥3)")
    return reasons


def test_corpus_is_non_empty_and_doctrine_only():
    passages = load_corpus_passages()
    assert passages, "el corpus quedó vacío tras Hallazgo 7"
    assert all(p.kind == "doctrine" for p in passages), "el corpus solo debe ser doctrina citable"
    assert all(p.text.strip() and p.source for p in passages), "todo pasaje con texto y lineage"


def test_every_corpus_passage_is_client_citable():
    """El gate: corre load_corpus_passages() completo y falla si CUALQUIER pasaje no es citable."""
    offenders = []
    for p in load_corpus_passages():
        v = _citability_violations(p.text)
        if v:
            offenders.append(f"  [{p.ref}] {', '.join(v)}\n      texto: {p.text[:140]}")
    assert not offenders, (
        "Pasajes NO aptos para cita directa a cliente en el corpus (Hallazgo 7).\n"
        "Una fuente del CORPUS_MANIFEST o un `rationale` de doctrina contiene tabla/código/"
        "config. Corrígelo (reescribe el rationale como prosa) o sácalo del manifest:\n"
        + "\n".join(offenders))


# ─── Regresión P12/P13/P14 (las 3 de la ronda de Hallazgo 5): la evidencia "rúbrica declarada"
# que ahora aparezca es SIEMPRE una frase de rationale limpia, nunca tabla ni comentario crudo.
# El gate de arriba lo garantiza sobre TODO el corpus; acá se demuestra concretamente vía el
# retrieval real de esas 3 temáticas (sin DB/LLM: solo el corpus estático de doctrina). ───
_P12_P14_QUERIES = [
    "papel del turismo la minería y la construcción en el crecimiento",           # P12
    "desempeño de las zonas francas y el comercio exterior frente a la economía",  # P13
    "desempeño reciente de la banca la energía y las telecomunicaciones",          # P14
]


def test_rubric_evidence_for_pilot_questions_is_clean_prose():
    for q in _P12_P14_QUERIES:
        for r in retrieve(q, top_k=5):
            v = _citability_violations(r.get("text", ""))
            assert not v, (
                f"La consulta {q!r} recuperó evidencia NO citable ({', '.join(v)}): "
                f"{r.get('text', '')[:140]}")
